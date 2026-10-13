"""Shared fixtures for item 2 tests: fake clock, claims, pseudonym key, policy builders."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from neurosphere_core.auth.jwt import VerifiedClaims
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    NoRevocationCheck,
    PolicyGrant,
    PolicyHead,
    PolicyRoleAssignment,
    PrincipalPolicy,
    PrincipalPseudonymizer,
    PseudonymKey,
    RevocationChecker,
    Role,
    ScopeDerivationConfig,
    ScopeDeriver,
    principal_document_id,
)
from neurosphere_core.cloud import CloudName

TENANT = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"
OTHER_TENANT = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
OBJECT_ID = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"
CUSTOMER = "contoso"
T0 = 1_800_000_000.0
KEY_MATERIAL = bytes(range(32))
KEY_REFERENCE = "https://ns-test-kv.vault.azure.net/secrets/principal-pseudonym-key"

FINANCE = "commercial:contoso:catalog:domain:finance"
OPERATIONS = "commercial:contoso:catalog:domain:operations"
HR = "commercial:contoso:catalog:domain:hr"
OTHER_CUSTOMER_FINANCE = "commercial:fabrikam:catalog:domain:finance"
GOV_FINANCE = "government:contoso:catalog:domain:finance"
AGENT = "commercial:contoso:foundry:agent:support-bot"
OTHER_AGENT = "commercial:contoso:foundry:agent:hr-bot"


class FakeClock:
    def __init__(self, now: float = T0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def datetime(self) -> datetime:
        return datetime.fromtimestamp(self.now, UTC)


def at(offset_seconds: float) -> datetime:
    return datetime.fromtimestamp(T0, UTC) + timedelta(seconds=offset_seconds)


def make_claims(
    *,
    object_id: str = OBJECT_ID,
    tenant_id: str = TENANT,
    cloud: CloudName = CloudName.COMMERCIAL,
    identity_type: str | None = "user",
    lifetime_seconds: float = 3600,
    **extra: Any,
) -> VerifiedClaims:
    fields: dict[str, Any] = {
        "issuer_kind": "entra",
        "cloud": cloud,
        "issuer": f"https://login.microsoftonline.com/{tenant_id}/v2.0",
        "audience": "api://neurosphere-test-api",
        "tenant_id": tenant_id,
        "object_id": object_id,
        "subject": "subject-" + object_id[:8],
        "token_version": "2.0",
        "issued_at": at(-60),
        "not_before": at(-60),
        "expires_at": at(lifetime_seconds),
        "identity_type": identity_type,
    }
    fields.update(extra)
    return VerifiedClaims(**fields)


def make_key(material: bytes = KEY_MATERIAL) -> PseudonymKey:
    return PseudonymKey(material, reference=KEY_REFERENCE)


def pseudonymizer() -> PrincipalPseudonymizer:
    return PrincipalPseudonymizer(make_key())


def principal_id_for(object_id: str = OBJECT_ID, kind: str = "person") -> str:
    pseudonym = pseudonymizer().pseudonym(TENANT, object_id)
    return f"commercial:{CUSTOMER}:entra:{kind}:{pseudonym}"


def role(
    role_: Role,
    *domains: str,
    expires_in: float | None = None,
    assignment_id: str | None = None,
) -> PolicyRoleAssignment:
    return PolicyRoleAssignment(
        assignment_id=assignment_id or f"ra-{role_.value}-{len(domains)}",
        role=role_,
        domain_ids=domains,
        expires_at=None if expires_in is None else at(expires_in),
    )


def grant(
    resource_id: str,
    *permissions: str,
    expires_in: float = 1800,
    grant_id: str = "g-1",
    reason: str = "incident review INC-42",
) -> PolicyGrant:
    return PolicyGrant.model_validate(
        {
            "grant_id": grant_id,
            "resource_id": resource_id,
            "permissions": list(permissions),
            "expires_at": at(expires_in),
            "reason": reason,
        }
    )


def principal_policy(
    *,
    memberships: tuple[str, ...] = (FINANCE, OPERATIONS),
    roles: tuple[PolicyRoleAssignment, ...] = (),
    grants: tuple[PolicyGrant, ...] = (),
    object_id: str = OBJECT_ID,
    kind: str = "person",
) -> PrincipalPolicy:
    pid = principal_id_for(object_id, kind)
    return PrincipalPolicy(
        id=principal_document_id(pid),
        customer_id=CUSTOMER,
        principal_id=pid,
        domain_memberships=memberships,
        role_assignments=roles,
        grants=grants,
    )


def make_repo(
    policy: PrincipalPolicy | None = None, *, version: str | None = "2026.10.01-1"
) -> InMemoryPolicyRepository:
    repo = InMemoryPolicyRepository()
    if version is not None:
        repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version=version))
    if policy is not None:
        repo.put_principal(policy)
    return repo


def make_deriver(
    repo: InMemoryPolicyRepository,
    *,
    clock: FakeClock | None = None,
    revocation_checker: RevocationChecker | None = None,
    **config: Any,
) -> ScopeDeriver:
    cfg = ScopeDerivationConfig(
        cloud=CloudName.COMMERCIAL, tenant_id=TENANT, customer_id=CUSTOMER, **config
    )
    return ScopeDeriver(
        cfg,
        policy_repository=repo,
        pseudonymizer=pseudonymizer(),
        revocation_checker=revocation_checker or NoRevocationCheck(),
        clock=clock or FakeClock(),
    )
