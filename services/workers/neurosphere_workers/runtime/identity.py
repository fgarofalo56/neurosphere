"""The worker's workload identity: scope derivation, permission recheck and the pseudonym key.

The worker has no end user. Its scope still comes from the one derivation path
(``ScopeDeriver.from_verified_claims`` over the Cosmos policy store), so it holds exactly the
domains the policy store grants its principal and loses them when the policy, a role expiry or a
revocation says so. There is no unrestricted bypass.

``EnvClaimsSource`` builds the ``VerifiedClaims`` of the worker's own workload principal from
configuration (``NS_WORKER_TENANT_ID``/``NS_AUTH_TENANT_ID`` and ``NS_WORKER_OBJECT_ID``); the
principal is only meaningful once an operator granted it in the policy store. Validating a real
managed-identity token instead is a deployment follow-up behind the same ``ClaimsSource`` seam.

The principal pseudonym key MUST equal the API's, otherwise ``HMAC(tenant:oid)`` differs and the
worker principal is unknown to the policy store. The derivation below mirrors the API's resolver
(``neurosphere_api.runtime.pseudonym``; workers may not import ``services/api``):
``NS_AUTH_PSEUDONYM_KEY`` plus ``NS_AUTH_PSEUDONYM_KEY_REFERENCE`` from the platform's Key Vault
reference, or, only when ``NS_ENV=local``, the fixed public development key.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from azure.cosmos.aio import CosmosClient
from neurosphere_core.auth.jwt import VerifiedClaims
from neurosphere_core.auth.jwt.config import normalize_tenant_id
from neurosphere_core.auth.revocation import (
    DEFAULT_REVOCATION_CONTAINER,
    CachedRevocationChecker,
    CosmosRevocationStore,
    load_revocation_settings,
)
from neurosphere_core.auth.scope import (
    CosmosPolicyRepository,
    PrincipalPseudonymizer,
    PseudonymKey,
    ScopeDerivationConfig,
    ScopeDeriver,
)
from neurosphere_core.auth.scope.pseudonym import MIN_KEY_BYTES
from neurosphere_core.cloud import Settings
from pydantic import ValidationError

from neurosphere_workers.projections.catalog import WorkloadScopeProvider
from neurosphere_workers.runtime.roles import RoleConfigError
from neurosphere_workers.runtime.settings import AuthSettings, StoreSettings, WorkerSettings

__all__ = [
    "EnvClaimsSource",
    "PolicyStack",
    "WorkerIdentity",
    "build_identity",
    "build_policy_stack",
    "resolve_pseudonym_key",
]

#: Same placeholder reference and label as ``neurosphere_api.runtime.pseudonym`` (a test pins it).
LOCAL_DEV_PSEUDONYM_KEY_REFERENCE: Final = (
    "https://ns-local-dev-only.vault.azure.net/secrets/local-dev-principal-pseudonym-key"
)
_LOCAL_DEV_LABEL: Final = b"neurosphere/local-dev/principal-pseudonym/v1"
_CLAIMS_LIFETIME: Final = timedelta(hours=1)
_AUDIENCE: Final = "neurosphere-worker"


def resolve_pseudonym_key(auth: AuthSettings, *, env: str) -> PseudonymKey:
    secret = auth.pseudonym_key
    value = secret.get_secret_value() if secret is not None else ""
    if not value:
        if env == "local":
            return PseudonymKey(
                hashlib.sha256(_LOCAL_DEV_LABEL).digest(),
                reference=LOCAL_DEV_PSEUDONYM_KEY_REFERENCE,
            )
        raise RoleConfigError("pseudonym_key_missing")
    if auth.pseudonym_key_reference is None:
        raise RoleConfigError("pseudonym_key_reference_missing")
    material = value.encode("utf-8")
    if len(material) < MIN_KEY_BYTES:
        raise RoleConfigError("pseudonym_key_invalid")
    try:
        return PseudonymKey(material, reference=auth.pseudonym_key_reference)
    except ValueError:
        raise RoleConfigError("pseudonym_key_invalid") from None


class EnvClaimsSource:
    """``ClaimsSource`` for the worker's own workload principal (``identity_type == "app"``)."""

    def __init__(self, settings: Settings, *, tenant_id: str, object_id: str) -> None:
        self._cloud = settings.cloud_profile.cloud
        self._login_host = settings.cloud_profile.login_host
        self._tenant = tenant_id
        self._object_id = object_id

    async def claims(self) -> VerifiedClaims:
        now = datetime.now(UTC)
        return VerifiedClaims(
            issuer_kind="entra",
            cloud=self._cloud,
            issuer=f"https://{self._login_host}/{self._tenant}/v2.0",
            audience=_AUDIENCE,
            tenant_id=self._tenant,
            object_id=self._object_id,
            subject=f"worker-{self._object_id[:8]}",
            token_version="2.0",  # noqa: S106 - JWT version label, not a secret
            issued_at=now - timedelta(seconds=60),
            not_before=now - timedelta(seconds=60),
            expires_at=now + _CLAIMS_LIFETIME,
            identity_type="app",
        )


@dataclass(frozen=True, slots=True)
class PolicyStack:
    """Policy store and revocation checker (what the permission recheck needs)."""

    policy: CosmosPolicyRepository
    revocation: CachedRevocationChecker
    key: PseudonymKey
    tenant_id: str


def build_policy_stack(
    settings: Settings,
    *,
    cosmos: CosmosClient,
    auth: AuthSettings,
    store: StoreSettings,
    tenant_id: str | None,
) -> PolicyStack:
    """Raises ``RoleConfigError`` (terminal for the role) for a missing tenant or key."""
    if tenant_id is None:
        raise RoleConfigError("tenant_id_missing")
    try:
        tenant = normalize_tenant_id(tenant_id)
    except ValueError:
        raise RoleConfigError("tenant_id_invalid") from None
    key = resolve_pseudonym_key(auth, env=settings.env)
    try:
        revocation_settings = load_revocation_settings()
    except ValidationError:
        raise RoleConfigError("revocation_settings_invalid") from None
    policy = CosmosPolicyRepository(
        cosmos, database=store.database, container=auth.policy_container
    )
    revocation_store = CosmosRevocationStore.from_client(
        cosmos,
        database=store.database,
        container=DEFAULT_REVOCATION_CONTAINER,
        retention_seconds=revocation_settings.retention_seconds,
    )
    checker = CachedRevocationChecker.from_settings(revocation_store, revocation_settings)
    return PolicyStack(policy=policy, revocation=checker, key=key, tenant_id=tenant)


class WorkerIdentity:
    """The worker's scope provider over a :class:`PolicyStack`."""

    def __init__(self, *, deriver: ScopeDeriver, scope_provider: WorkloadScopeProvider) -> None:
        self.deriver = deriver
        self.scope_provider = scope_provider


def build_identity(
    settings: Settings,
    *,
    stack: PolicyStack,
    worker: WorkerSettings,
    customer_id: str,
) -> WorkerIdentity:
    """Raises ``RoleConfigError`` when the worker's own object id is not configured."""
    if worker.object_id is None:
        raise RoleConfigError("worker_object_id_missing")
    try:
        config = ScopeDerivationConfig(
            cloud=settings.cloud_profile.cloud, tenant_id=stack.tenant_id, customer_id=customer_id
        )
    except ValidationError:
        raise RoleConfigError("scope_config_invalid") from None
    deriver = ScopeDeriver(
        config,
        policy_repository=stack.policy,
        pseudonymizer=PrincipalPseudonymizer(stack.key),
        revocation_checker=stack.revocation,
    )
    claims = EnvClaimsSource(settings, tenant_id=stack.tenant_id, object_id=worker.object_id)
    return WorkerIdentity(deriver=deriver, scope_provider=WorkloadScopeProvider(deriver, claims))
