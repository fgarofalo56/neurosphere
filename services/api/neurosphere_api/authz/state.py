"""Authorization wiring: what ``configure_authz`` installs on ``app.state`` (PRP-06 item 3).

The PRP-05 app factory is not edited here. A caller (the app factory, ``main.py`` or a test)
builds the token validator (item 1) and the scope deriver (item 2) and calls
:func:`configure_authz`. Until that happens every protected route fails closed with 503
(reason ``authz_unconfigured``): an unwired deployment never serves a protected route.

The validator and deriver are typed by protocol so tests and later PRPs can substitute fakes,
but the production pair is ``JwtValidator`` + ``ScopeDeriver``. When both concrete types are
passed, their cloud and tenant bindings must agree or wiring fails at startup.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

from fastapi import FastAPI, Request
from neurosphere_core.auth.jwt import Clock, JwtValidator, VerifiedClaims
from neurosphere_core.auth.scope import ScopeDerivation, ScopeDeriver
from neurosphere_core.errors import DependencyTransientError, InvalidSchemaError

from neurosphere_api.authz.recorder import DenialRecorder

__all__ = [
    "DEFAULT_AUTHZ_TIMEOUT_SECONDS",
    "STATE_ATTRIBUTE",
    "AuthzState",
    "ScopeSource",
    "TokenAuthenticator",
    "configure_authz",
    "get_authz_state",
]

#: Upper bound on token validation plus scope derivation for one request. The deriver has its
#: own per-call store timeout; this outer bound also covers JWKS fetches and any custom source.
DEFAULT_AUTHZ_TIMEOUT_SECONDS: Final = 5.0
STATE_ATTRIBUTE: Final = "authz"


@runtime_checkable
class TokenAuthenticator(Protocol):
    """Item 1 shape: ``Authorization`` header value in, ``VerifiedClaims`` out, or raise."""

    async def authenticate(self, authorization: str | None) -> VerifiedClaims: ...


@runtime_checkable
class ScopeSource(Protocol):
    """Item 2 shape: verified claims in, server-derived scope out, or raise."""

    async def derive(self, claims: VerifiedClaims) -> ScopeDerivation: ...


@dataclass(frozen=True, slots=True)
class AuthzState:
    authenticator: TokenAuthenticator
    scope_source: ScopeSource
    clock: Clock
    timeout_seconds: float
    denial_recorder: DenialRecorder | None
    public_paths: frozenset[str]


def configure_authz(
    app: FastAPI,
    *,
    authenticator: TokenAuthenticator,
    scope_source: ScopeSource,
    clock: Clock = time.time,
    timeout_seconds: float = DEFAULT_AUTHZ_TIMEOUT_SECONDS,
    denial_recorder: DenialRecorder | None = None,
    extra_public_paths: Iterable[str] = (),
) -> AuthzState:
    """Install the authorization dependencies' collaborators on ``app.state.authz``.

    ``extra_public_paths`` extends the public allowlist used by the route inventory; it does not
    change what ``require`` does (a route that depends on ``require`` is always protected).
    """
    # Local import: routes.py imports this module for the state type.
    from neurosphere_api.authz.routes import public_paths_for

    if not isinstance(authenticator, TokenAuthenticator):
        raise InvalidSchemaError("authenticator lacks authenticate()", reason="config")
    if not isinstance(scope_source, ScopeSource):
        raise InvalidSchemaError("scope source lacks derive()", reason="config")
    if not timeout_seconds > 0:
        raise InvalidSchemaError("authz timeout must be positive", reason="config")
    _check_binding(authenticator, scope_source)
    state = AuthzState(
        authenticator=authenticator,
        scope_source=scope_source,
        clock=clock,
        timeout_seconds=float(timeout_seconds),
        denial_recorder=denial_recorder,
        public_paths=public_paths_for(app, extra=extra_public_paths),
    )
    setattr(app.state, STATE_ATTRIBUTE, state)
    return state


def _check_binding(authenticator: TokenAuthenticator, scope_source: ScopeSource) -> None:
    if not isinstance(authenticator, JwtValidator) or not isinstance(scope_source, ScopeDeriver):
        return
    jwt_cfg, scope_cfg = authenticator.config, scope_source.config
    if jwt_cfg.cloud is not scope_cfg.cloud or jwt_cfg.tenant_id != scope_cfg.tenant_id:
        raise InvalidSchemaError(
            "token validator and scope deriver are bound to different clouds or tenants",
            reason="config",
        )


def get_authz_state(request: Request) -> AuthzState:
    """The installed state, or 503 ``authz_unconfigured`` (never an implicit allow)."""
    state = getattr(request.app.state, STATE_ATTRIBUTE, None)
    if not isinstance(state, AuthzState):
        raise DependencyTransientError(
            "authorization is not configured", reason="authz_unconfigured"
        )
    return state
