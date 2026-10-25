"""Authz builder: Entra token validation, scope derivation, policy store and revocation.

Production wiring (no other path exists from ``main``):

* ``policy_store``: ``CosmosPolicyRepository`` on ``NS_STORE_DATABASE`` and
  ``NS_AUTH_POLICY_CONTAINER``.
* ``revocation``: ``CosmosRevocationStore`` on ``revocations`` behind a
  ``CachedRevocationChecker`` (``NS_REVOCATION_*``).
* ``authz``: ``create_jwt_validator`` over ``httpx`` against the tenant's Entra JWKS
  (``JwtConfig.from_settings`` with the deployment's cloud, ``NS_AUTH_TENANT_ID`` and
  ``NS_AUTH_AUDIENCES``; no other key source is configured) and a ``ScopeDeriver`` over the two
  stores above plus the ``PrincipalPseudonymizer`` from :func:`resolve_pseudonym_key`, bound
  to ``NS_AUTH_CUSTOMER_ID``; then ``configure_authz``.

Each failure is a readiness reason; protected routes keep answering 503 ``authz_unconfigured``
until ``authz`` is ``ok``. Test code may replace the authenticator, the scope source or either
store through ``CompositionOverrides``; ``main.create`` never does.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Final

import httpx
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
    CosmosPolicyRepository,
    PolicyRepository,
    PrincipalPseudonymizer,
    ScopeDerivationConfig,
    ScopeDeriver,
)
from neurosphere_core.errors import InvalidSchemaError
from pydantic import ValidationError

from neurosphere_api.authz import ScopeSource, TokenAuthenticator, configure_authz
from neurosphere_api.runtime.builders import (
    AUTH_SETTINGS,
    AUTHENTICATOR,
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

__all__ = ["BUILDER", "COMPONENTS", "build"]

COMPONENTS: Final = ("authz", "policy_store", "revocation")


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


def _deriver(
    ctx: BuildContext,
    auth: AuthSettings,
    tenant_id: str,
    policy: PolicyRepository | None,
    checker: CachedRevocationChecker | None,
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
    try:
        key = resolve_pseudonym_key(auth, env=ctx.settings.env)
    except InvalidSchemaError as exc:
        raise ComponentUnavailableError(exc.reason or "pseudonym_key_invalid") from None
    pseudonymizer = PrincipalPseudonymizer(key)
    deriver = ScopeDeriver(
        config,
        policy_repository=policy,
        pseudonymizer=pseudonymizer,
        revocation_checker=checker,
        clock=clock,
    )
    ctx.publish(PSEUDONYMIZER, pseudonymizer)
    ctx.publish(SCOPE_DERIVER, deriver)
    hooks = RevocationHookRegistry()
    hooks.register_cache_invalidator("revocation-checker", checker.invalidate_principal)
    hooks.register_cache_invalidator("scope-deriver", deriver.invalidate_principal)
    ctx.publish(REVOCATION_HOOKS, hooks)
    return deriver


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


def _authz(
    ctx: BuildContext,
    auth: AuthSettings,
    policy: PolicyRepository | None,
    checker: CachedRevocationChecker | None,
    clock: Clock,
) -> None:
    tenant_id = _tenant(auth)
    scope_source: ScopeSource
    if ctx.overrides.scope_source is not None:
        scope_source = ctx.overrides.scope_source
    else:
        scope_source = _deriver(ctx, auth, tenant_id, policy, checker, clock)
    authenticator = _authenticator(ctx, auth, tenant_id, clock)
    try:
        configure_authz(
            ctx.app,
            authenticator=authenticator,
            scope_source=scope_source,
            clock=clock,
            denial_recorder=ctx.overrides.denial_recorder,
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
    if checker is not None:
        ctx.publish(REVOCATION_CHECKER, checker)
    ctx.attempt("authz", lambda: _authz(ctx, auth, policy, checker, clock))


BUILDER: Final = BuilderSpec("authz", COMPONENTS, build)
