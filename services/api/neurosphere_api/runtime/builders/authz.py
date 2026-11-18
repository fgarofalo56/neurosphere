"""Authz builder: Entra token validation, scope derivation, policy store and revocation.

Production wiring (no other path exists from ``main``):

* ``policy_store``: ``CosmosPolicyRepository`` on ``NS_STORE_DATABASE`` and
  ``NS_AUTH_POLICY_CONTAINER``.
* ``revocation``: ``CosmosRevocationStore`` on ``revocations`` behind a
  ``CachedRevocationChecker`` (``NS_REVOCATION_*``).
* ``REVOCATION_HOOKS``: the ONE ``RevocationHookRegistry`` of the composition, published as soon
  as the checker exists (independent of how the scope source is built), with the checker's and,
  when composed, the deriver's ``invalidate_principal`` as cache invalidators. Push-session
  closers register on it in LATER builders: the data builder registers the realtime
  ``GatewayRegistry`` as push registry ``websocket`` (PRP-06 C13, PRP-18), so a revocation fan-out
  calls its ``close_for_principal``. A composition without the realtime gateway simply has no
  push registries; a failing closer never aborts the other hooks (``RevocationHookRegistry``).
* ``authz``: ``create_jwt_validator`` over ``httpx`` against the tenant's Entra JWKS
  (``JwtConfig.from_settings`` with the deployment's cloud, ``NS_AUTH_TENANT_ID`` and
  ``NS_AUTH_AUDIENCES``; no other key source is configured) and a ``ScopeDeriver`` over the two
  stores above plus the ``PrincipalPseudonymizer`` from :func:`resolve_pseudonym_key`, bound
  to ``NS_AUTH_CUSTOMER_ID``; then ``configure_authz``.
* ``CLAIM_ROLE_MAPPING`` (PRP-138): ``NS_AUTH_ROLE_MAPPINGS`` parsed with
  ``parse_claim_role_mapping``. Unset means off and the composition is exactly as without it. A
  malformed mapping, or an explicit domain id of another cloud or customer, fails ``authz`` with
  ``role_mapping_invalid``; a mapping whose tenant is not ``NS_AUTH_TENANT_ID`` or whose audience
  is not one of ``NS_AUTH_AUDIENCES`` fails it with ``role_mapping_binding_mismatch``. A valid
  mapping is published and handed to the deriver with a domain directory that resolves the
  ``DOMAIN_REGISTRY`` per call (the admin_platform builder publishes it later), the
  :class:`ClaimGrantAuditObserver` (audit repository resolved per call); the local token
  issuer is accepted for mapping only in ``NS_ENV=local`` (``deriver_mapping_options``).
* ``denial_recorder``: :class:`AuditDenialRecorder`, appending a ``denied`` record to the
  ``AUDIT_REPOSITORY`` for every refused ``require`` check (PRP-06: a denied attempt is audited
  too). The data builder publishes that repository AFTER this builder runs, so the recorder
  resolves it at record time; while it is absent every record attempt raises, which
  ``require`` turns into 503 ``audit_write_failed`` on a mutating request (fail closed) and a
  logged warning plus the 403 on a safe one. A recorder failure never turns a deny into an allow.

Each failure is a readiness reason; protected routes keep answering 503 ``authz_unconfigured``
until ``authz`` is ``ok``. Test code may replace the authenticator, the scope source, the denial
recorder or either store through ``CompositionOverrides``; ``main.create`` never does.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Callable
from typing import Final

import httpx
from neurosphere_contracts.admin.v1.domain_definition import DomainDefinition
from neurosphere_contracts.audit.v1.audit_record import Subject
from neurosphere_core.admin.platform import DomainRegistry
from neurosphere_core.audit import (
    AuditContext,
    AuditRepository,
    build_denied,
    find_sensitive_content,
    make_subject,
)
from neurosphere_core.audit.chains import is_chain_customer_id
from neurosphere_core.auth.jwt import Clock, JwtConfig, create_jwt_validator
from neurosphere_core.auth.jwt.config import normalize_tenant_id
from neurosphere_core.auth.jwt.jwks import DEFAULT_FETCH_TIMEOUT_SECONDS
from neurosphere_core.auth.revocation import (
    DEFAULT_REVOCATION_CONTAINER,
    CachedRevocationChecker,
    CosmosRevocationStore,
    RevocationHookRegistry,
    RevocationStore,
    load_revocation_settings,
)
from neurosphere_core.auth.scope import (
    ClaimRoleMapping,
    ClaimRoleMappingError,
    CosmosPolicyRepository,
    PolicyRepository,
    PrincipalPseudonymizer,
    ScopeDerivationConfig,
    ScopeDeriver,
    customer_control_domain_id,
    parse_claim_role_mapping,
)
from neurosphere_core.errors import DependencyTransientError, InvalidSchemaError
from neurosphere_core.hitl.auditing import audit_chain_for
from neurosphere_core.scope import IdentityScope
from pydantic import ValidationError

from neurosphere_api.actions.common import audit_correlation_id
from neurosphere_api.authz import (
    ClaimGrantAuditObserver,
    ClaimMappingStats,
    DenialRecorder,
    DeniedAttempt,
    ScopeSource,
    TokenAuthenticator,
    configure_authz,
)
from neurosphere_api.authz.claim_audit import (
    deriver_mapping_options,
    install_claim_mapping_stats,
)
from neurosphere_api.runtime.builders import (
    AUDIT_REPOSITORY,
    AUTH_SETTINGS,
    AUTHENTICATOR,
    CLAIM_ROLE_MAPPING,
    DOMAIN_REGISTRY,
    POLICY_REPOSITORY,
    PSEUDONYMIZER,
    REVOCATION_CHECKER,
    REVOCATION_HOOKS,
    REVOCATION_STORE,
    SCOPE_DERIVER,
    SCOPE_SOURCE,
    BuildContext,
    BuilderSpec,
    ComponentUnavailableError,
)
from neurosphere_api.runtime.pseudonym import resolve_pseudonym_key
from neurosphere_api.runtime.settings import AuthSettings

__all__ = [
    "BUILDER",
    "COMPONENTS",
    "DENIAL_CHAIN_NAME",
    "AuditDenialRecorder",
    "RegistryDomainDirectory",
    "build",
]

COMPONENTS: Final = ("authz", "policy_store", "revocation")

#: Chain ``<customer_id>.<this>`` holds denials whose target is not a domain the caller belongs
#: to (or could not be resolved). A target domain the caller IS a member of is recorded on that
#: domain's chain (``audit_chain_for``), beside the domain's other records. Chain names never
#: come from request input.
DENIAL_CHAIN_NAME: Final = "authz-denials"

_REASON_CODE: Final = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")
#: ``AuditRecord.correlation_id`` pattern (contracts ``audit/v1/audit-record.schema.json``).
_CORRELATION_ID: Final = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
#: ``ScopeDerivationConfig.customer_id`` pattern: a slug that may contain ``.``. A customer id that
#: matches it but not the audit-chain rule (a dotted customer) is ``customer_id_invalid`` (#206.1).
_DERIVATION_CUSTOMER: Final = re.compile(r"^[a-z0-9._-]{1,128}$")
#: Prefix ``audit_correlation_id`` adds; also used for a generated id.
_CORRELATION_PREFIX: Final = "corr-"


class AuditDenialRecorder:
    """``DenialRecorder`` that appends a ``denied`` audit record (PRP-06 C11 metadata only).

    The record carries the actor pseudonym, principal kind and scope hash from the server-derived
    scope, the permission as the operation, ``forbidden`` plus the deny reason code, the
    request's correlation id (audit-safe form; generated when absent or unusable, see
    :func:`_correlation_id`), and the target as a canonical-id subject with no state. A
    target that is not a valid canonical id, or that the metadata guard would reject (for
    example a GUID-shaped person id from a forged path), is left out rather than failing the
    write; the denial itself is always recorded. Request bodies, tokens and paths are never
    stored.

    ``repository`` is resolved per call (see the module docstring); ``None`` raises.
    """

    def __init__(self, repository: Callable[[], AuditRepository | None]) -> None:
        self._repository = repository

    async def record_denial(self, attempt: DeniedAttempt) -> None:
        repository = self._repository()
        if repository is None:
            raise DependencyTransientError(
                "audit store is not configured", reason="audit_store_unconfigured"
            )
        scope = attempt.scope
        ctx = AuditContext.from_scope(
            scope,
            correlation_id=_correlation_id(attempt.correlation_id),
            operation=attempt.permission,
            channel="rest",
        )
        draft = build_denied(
            ctx, code="forbidden", reason=_reason_code(attempt.reason), subject=_subject(attempt)
        )
        await repository.append(_chain(scope, attempt.domain_id), draft)


def _correlation_id(request_id: str | None) -> str:
    """The request's correlation id in audit-safe form, else a server-generated one.

    ``request_id`` is the middleware-bound id (a validated caller header or a UUID4). It is
    converted with the same ``audit_correlation_id`` the action/HITL/catalog routes use, then
    checked against the audit record's correlation id pattern and the metadata guard; anything
    that would fail either (so would make the denial write fail) is replaced, never echoed.
    """
    if request_id is not None:
        candidate = audit_correlation_id(request_id)
        if (
            candidate != _CORRELATION_PREFIX  # an empty or dashes-only id identifies nothing
            and _CORRELATION_ID.fullmatch(candidate)
            and not find_sensitive_content({"correlation_id": candidate})
        ):
            return candidate
    return f"{_CORRELATION_PREFIX}{uuid.uuid4().hex}"


def _reason_code(reason: str) -> str:
    """The deny reason if it is a contract reason code, else the generic ``forbidden``."""
    if 0 < len(reason) <= 64 and reason[0].isalpha() and set(reason) <= _REASON_CODE:
        return reason
    return "forbidden"


def _chain(scope: IdentityScope, domain_id: str | None) -> str:
    """The member domain's chain, else ``<customer>.authz-denials``.

    A member domain whose chain cannot be encoded (a name outside the chain pattern, too long, or
    a reserved customer-level name; #206.2) falls back to the customer denial chain: the denial
    is always recorded, never turned into a 503 by the chain name.
    """
    if domain_id is not None and domain_id in scope.allowed_domains:
        try:
            return audit_chain_for(scope.customer_id, domain_id)
        except InvalidSchemaError:
            pass  # unencodable member domain: record on the customer denial chain instead
    return f"{scope.customer_id}.{DENIAL_CHAIN_NAME}"


def _subject(attempt: DeniedAttempt) -> Subject | None:
    target = attempt.resource_id or attempt.domain_id
    if target is None:
        return None
    parts = target.split(":")
    if len(parts) < 5:
        return None
    try:
        subject = make_subject(target, parts[3])
    except ValidationError:
        return None  # not a canonical id: the denial is still recorded, without a target
    if find_sensitive_content({"subject": subject.model_dump(mode="json")}):
        return None
    return subject


def _denial_recorder(ctx: BuildContext) -> DenialRecorder:
    if ctx.overrides.denial_recorder is not None:
        return ctx.overrides.denial_recorder
    return AuditDenialRecorder(lambda: ctx.maybe_shared(AUDIT_REPOSITORY))


class _HttpxCloser:
    """Adapts ``httpx.AsyncClient.aclose`` to the ``ClientLifetime`` ``close`` contract."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def close(self) -> None:
        await self._client.aclose()


def _policy_repository(ctx: BuildContext, auth: AuthSettings) -> PolicyRepository:
    if ctx.overrides.policy_repository is not None:
        return ctx.overrides.policy_repository
    return CosmosPolicyRepository(
        ctx.cosmos_client(),
        database=ctx.store_settings().database,
        container=auth.policy_container,
    )


def _revocation_checker(ctx: BuildContext, clock: Clock) -> CachedRevocationChecker:
    try:
        revocation_settings = load_revocation_settings()
    except ValidationError:
        raise ComponentUnavailableError("revocation_settings_invalid") from None
    store: RevocationStore
    if ctx.overrides.revocation_store is not None:
        store = ctx.overrides.revocation_store
    else:
        store = CosmosRevocationStore.from_client(
            ctx.cosmos_client(),
            database=ctx.store_settings().database,
            container=DEFAULT_REVOCATION_CONTAINER,
            retention_seconds=revocation_settings.retention_seconds,
        )
    ctx.publish(REVOCATION_STORE, store)
    return CachedRevocationChecker.from_settings(store, revocation_settings, clock=clock)


def _tenant(auth: AuthSettings) -> str:
    if auth.tenant_id is None:
        raise ComponentUnavailableError("tenant_id_missing")
    try:
        return normalize_tenant_id(auth.tenant_id)
    except ValueError:
        raise ComponentUnavailableError("tenant_id_invalid") from None


class RegistryDomainDirectory:
    """``DomainDirectory`` over the ``DOMAIN_REGISTRY``, resolved on every call (PRP-138).

    The admin_platform builder publishes the registry after this builder ran, so it cannot be
    captured at build time. Not published (or failing) raises; the deriver denies with
    ``domain_directory_unavailable`` and never falls back to the control domain alone. The
    reserved control domain is left out: an ``all`` entry reaches it only through its own
    ``customer_control`` flag (PRP-138 clarification 2).
    """

    def __init__(self, registry: Callable[[], DomainRegistry | None], *, cloud: str) -> None:
        self._registry = registry
        self._cloud = cloud

    async def active_domain_ids(self, customer_id: str) -> tuple[str, ...]:
        registry = self._registry()
        if registry is None:
            raise DependencyTransientError(
                "domain registry is not configured", reason="domain_directory_unavailable"
            )
        # DomainRegistry has no public listing yet; ``_all`` is its own active-domain read.
        documents = await registry._all(customer_id, include_retired=False)
        control = customer_control_domain_id(self._cloud, customer_id)
        domains: list[str] = []
        for document in documents:
            if document.status != "active" or not isinstance(document.body, DomainDefinition):
                continue
            domain_id = document.body.domain_id.root
            if domain_id != control:
                domains.append(domain_id)
        return tuple(domains)


def _claim_mapping(
    auth: AuthSettings, tenant_id: str, config: ScopeDerivationConfig
) -> ClaimRoleMapping | None:
    """Parse and check ``NS_AUTH_ROLE_MAPPINGS``; ``None`` when unset (mapping off)."""
    try:
        mapping = parse_claim_role_mapping(auth.role_mappings)
    except ClaimRoleMappingError:
        raise ComponentUnavailableError("role_mapping_invalid") from None
    if mapping is None:
        return None
    prefix = f"{config.cloud.value}:{config.customer_id}:"
    for entry in mapping.entries:
        if entry.domains != "all" and not all(d.startswith(prefix) for d in entry.domains):
            raise ComponentUnavailableError("role_mapping_invalid")
    if mapping.tenant_id != tenant_id or mapping.audience not in auth.audiences:
        raise ComponentUnavailableError("role_mapping_binding_mismatch")
    return mapping


def _deriver(
    ctx: BuildContext,
    auth: AuthSettings,
    tenant_id: str,
    policy: PolicyRepository | None,
    checker: CachedRevocationChecker | None,
    hooks: RevocationHookRegistry | None,
    clock: Clock,
) -> ScopeDeriver:
    if policy is None:
        raise ComponentUnavailableError("policy_store_unavailable")
    if checker is None:
        raise ComponentUnavailableError("revocation_unavailable")
    customer_id = auth.resolved_customer_id(ctx.settings.env)
    if customer_id is None:
        raise ComponentUnavailableError("customer_id_missing")
    try:
        config = ScopeDerivationConfig(
            cloud=ctx.settings.cloud_profile.cloud, tenant_id=tenant_id, customer_id=customer_id
        )
    except ValidationError:
        raise ComponentUnavailableError("scope_config_invalid") from None
    mapping = _claim_mapping(auth, tenant_id, config)
    try:
        key = resolve_pseudonym_key(auth, env=ctx.settings.env)
    except InvalidSchemaError as exc:
        raise ComponentUnavailableError(exc.reason or "pseudonym_key_invalid") from None
    pseudonymizer = PrincipalPseudonymizer(key)
    # Mapping off: no mapping argument is passed, so the deriver keeps every default.
    directory: RegistryDomainDirectory | None = None
    observer: ClaimGrantAuditObserver | None = None
    if mapping is not None:
        stats = ClaimMappingStats(mapping)
        directory = RegistryDomainDirectory(
            lambda: ctx.maybe_shared(DOMAIN_REGISTRY), cloud=config.cloud.value
        )
        observer = ClaimGrantAuditObserver(lambda: ctx.maybe_shared(AUDIT_REPOSITORY), stats=stats)
        install_claim_mapping_stats(ctx.app.state, stats)
        ctx.publish(CLAIM_ROLE_MAPPING, mapping)
    deriver = ScopeDeriver(
        config,
        policy_repository=policy,
        pseudonymizer=pseudonymizer,
        revocation_checker=checker,
        clock=clock,
        **deriver_mapping_options(
            mapping, domain_directory=directory, observer=observer, env=ctx.settings.env
        ),
    )
    ctx.publish(PSEUDONYMIZER, pseudonymizer)
    ctx.publish(SCOPE_DERIVER, deriver)
    if hooks is not None:
        hooks.register_cache_invalidator("scope-deriver", deriver.invalidate_principal)
    return deriver


def _revocation_hooks(
    ctx: BuildContext, checker: CachedRevocationChecker
) -> RevocationHookRegistry:
    """Publish the composition's hook registry; later builders add push-session closers."""
    hooks = RevocationHookRegistry()
    hooks.register_cache_invalidator("revocation-checker", checker.invalidate_principal)
    ctx.publish(REVOCATION_HOOKS, hooks)
    return hooks


def _authenticator(
    ctx: BuildContext, auth: AuthSettings, tenant_id: str, clock: Clock
) -> TokenAuthenticator:
    if ctx.overrides.authenticator is not None:
        return ctx.overrides.authenticator
    if not auth.audiences:
        raise ComponentUnavailableError("audiences_missing")
    try:
        config = JwtConfig.from_settings(
            ctx.settings, tenant_id=tenant_id, audiences=auth.audiences
        )
    except InvalidSchemaError:
        raise ComponentUnavailableError("jwt_config_invalid") from None
    client = httpx.AsyncClient(timeout=DEFAULT_FETCH_TIMEOUT_SECONDS, follow_redirects=False)
    ctx.lifetime.register(_HttpxCloser(client))
    return create_jwt_validator(config, client, clock=clock)


def _check_customer_id(ctx: BuildContext, auth: AuthSettings) -> None:
    """Refuse a customer id that cannot name audit chains (#206.1: a dotted customer).

    Every audited write would otherwise fail one by one with ``invalid_chain_id``; failing the
    ``authz`` component at boot (``customer_id_invalid``) keeps protected routes at 503 instead.
    """
    customer_id = auth.resolved_customer_id(ctx.settings.env)
    if customer_id is None or not _DERIVATION_CUSTOMER.fullmatch(customer_id):
        return  # missing or not a slug at all: the deriver reports it (customer_id_missing, ...)
    if not is_chain_customer_id(customer_id):
        raise ComponentUnavailableError("customer_id_invalid")


def _authz(
    ctx: BuildContext,
    auth: AuthSettings,
    policy: PolicyRepository | None,
    checker: CachedRevocationChecker | None,
    hooks: RevocationHookRegistry | None,
    clock: Clock,
) -> None:
    _check_customer_id(ctx, auth)
    tenant_id = _tenant(auth)
    scope_source: ScopeSource
    if ctx.overrides.scope_source is not None:
        scope_source = ctx.overrides.scope_source
    else:
        scope_source = _deriver(ctx, auth, tenant_id, policy, checker, hooks, clock)
    authenticator = _authenticator(ctx, auth, tenant_id, clock)
    try:
        configure_authz(
            ctx.app,
            authenticator=authenticator,
            scope_source=scope_source,
            clock=clock,
            denial_recorder=_denial_recorder(ctx),
        )
    except InvalidSchemaError:
        raise ComponentUnavailableError("authz_binding_mismatch") from None
    ctx.publish(AUTHENTICATOR, authenticator)
    ctx.publish(SCOPE_SOURCE, scope_source)


def build(ctx: BuildContext) -> None:
    try:
        auth = ctx.auth_settings()
    except ComponentUnavailableError as exc:
        for name in COMPONENTS:
            ctx.failed(name, exc.reason)
        return
    ctx.publish(AUTH_SETTINGS, auth)
    clock: Callable[[], float] = ctx.overrides.clock or time.time

    policy = ctx.attempt("policy_store", lambda: _policy_repository(ctx, auth))
    if policy is not None:
        ctx.publish(POLICY_REPOSITORY, policy)
    checker = ctx.attempt("revocation", lambda: _revocation_checker(ctx, clock))
    hooks: RevocationHookRegistry | None = None
    if checker is not None:
        ctx.publish(REVOCATION_CHECKER, checker)
        hooks = _revocation_hooks(ctx, checker)
    ctx.attempt("authz", lambda: _authz(ctx, auth, policy, checker, hooks, clock))


BUILDER: Final = BuilderSpec("authz", COMPONENTS, build)
