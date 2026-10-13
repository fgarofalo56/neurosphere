"""FastAPI authorization dependencies: ``current_scope`` and ``require`` (PRP-06 item 3).

``current_scope`` reads exactly one request input, the ``Authorization`` header, and passes it
to the item 1 validator; the resulting ``VerifiedClaims`` go to the item 2 deriver, which reads
only claims and the policy store. Headers other than ``Authorization``, query strings, bodies,
cookies and path parameters never reach scope derivation. FastAPI caches the dependency per
request, so a route with several ``require`` dependencies derives the scope once.

Outcomes are exactly three, all through ``neurosphere_core.errors``:

* ``unauthorized`` (401): missing, malformed, ambiguous or invalid token (item 1 reasons).
* ``forbidden`` (403): the derived scope lacks the permission on the target, or the principal is
  revoked. Reasons: ``permission_missing``, ``target_out_of_scope``, ``target_unresolved``.
* ``dependency_transient`` (503/502): policy store, revocation or key infrastructure failed or
  timed out, or authorization is not configured. Never an allow.

There is no allow-on-error branch: every ``except`` clause in this package re-raises (an AST test
in ``services/api/tests/authz/test_fail_closed.py`` enforces it).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Final

from fastapi import Depends, Request
from neurosphere_core.auth.scope import (
    Permission,
    ScopeDerivation,
    domains_with_permission,
    permits,
)
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    NeuroSphereError,
    UnauthorizedError,
)
from neurosphere_core.observability import get_logger
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz.recorder import SAFE_METHODS, DeniedAttempt
from neurosphere_api.authz.state import AuthzState, get_authz_state

__all__ = [
    "PERMISSION_MARKER",
    "AuthzTarget",
    "PermissionDependency",
    "ResourceResolver",
    "current_derivation",
    "current_scope",
    "domain_from_path",
    "require",
    "resource_from_path",
]

#: Attribute set on every dependency built by :func:`require`; the route inventory reads it.
PERMISSION_MARKER: Final = "__ns_permission__"

_LOG = get_logger("neurosphere_api.authz")
_PASSTHROUGH_ERRORS: Final = (UnauthorizedError, ForbiddenError, DependencyTransientError)


@dataclass(frozen=True, slots=True)
class AuthzTarget:
    """What a route acts on: a canonical domain id, a canonical resource id, or both.

    Built from the route's path parameters by a :data:`ResourceResolver`. It is the *target* of
    the check, never an input to the scope: a forged value can only produce a deny.
    """

    domain_id: str | None = None
    resource_id: str | None = None

    def __post_init__(self) -> None:
        if self.domain_id is None and self.resource_id is None:
            raise ValueError("AuthzTarget needs a domain_id or a resource_id")


ResourceResolver = Callable[[Request, IdentityScope], AuthzTarget | None]
PermissionDependency = Callable[..., Awaitable[IdentityScope]]


# --------------------------------------------------------------------------- scope


async def current_derivation(
    request: Request, state: Annotated[AuthzState, Depends(get_authz_state)]
) -> ScopeDerivation:
    """Validate the bearer token and derive the scope (with the policy ids used, for audit)."""
    authorization = _authorization_header(request)
    try:
        async with asyncio.timeout(state.timeout_seconds):
            claims = await state.authenticator.authenticate(authorization)
            derivation = await state.scope_source.derive(claims)
    except _PASSTHROUGH_ERRORS:
        raise
    except TimeoutError as exc:
        raise DependencyTransientError("authorization timed out", reason="authz_timeout") from exc
    except Exception as exc:
        # Includes NeuroSphereError subclasses outside the three authz outcomes.
        raise DependencyTransientError(
            "authorization unavailable", reason="authz_unavailable"
        ) from exc
    if not isinstance(derivation, ScopeDerivation) or not isinstance(
        derivation.scope, IdentityScope
    ):
        raise DependencyTransientError(
            "scope source returned an invalid scope", reason="authz_invalid_scope"
        )
    return derivation


async def current_scope(
    derivation: Annotated[ScopeDerivation, Depends(current_derivation)],
) -> IdentityScope:
    """The caller's server-derived ``IdentityScope``. Authentication only; no permission."""
    return derivation.scope


def _authorization_header(request: Request) -> str | None:
    values = request.headers.getlist("authorization")
    if len(values) > 1:
        raise UnauthorizedError("bearer token required", reason="ambiguous_token")
    return values[0] if values else None


# --------------------------------------------------------------------------- targets


def domain_from_path(param: str) -> ResourceResolver:
    """Resolver: the canonical domain id is the path parameter ``param``."""

    def resolve(request: Request, scope: IdentityScope) -> AuthzTarget | None:
        value = request.path_params.get(param)
        return AuthzTarget(domain_id=value) if isinstance(value, str) and value else None

    return resolve


def resource_from_path(param: str, *, domain_param: str | None = None) -> ResourceResolver:
    """Resolver: canonical resource id from ``param`` (optionally its domain from another)."""

    def resolve(request: Request, scope: IdentityScope) -> AuthzTarget | None:
        value = request.path_params.get(param)
        if not isinstance(value, str) or not value:
            return None
        domain = request.path_params.get(domain_param) if domain_param else None
        return AuthzTarget(
            domain_id=domain if isinstance(domain, str) and domain else None,
            resource_id=value,
        )

    return resolve


# --------------------------------------------------------------------------- require


def require(
    permission: Permission | str, resource: ResourceResolver | None = None
) -> PermissionDependency:
    """Dependency factory: 403 unless the derived scope holds ``permission`` on the target.

    With ``resource`` the check is :func:`permits` on the resolved domain or resource. Without it
    the check is that the scope holds ``permission`` on at least one domain (unexpired role) or
    one resource (unexpired grant); the route must still filter its data by the returned scope.
    A ``ForbiddenError`` raised by the resolver is recorded as a denied attempt like any other
    denial. Unknown permission names fail at declaration time (startup), not at request time.
    """
    try:
        perm = Permission(permission)
    except ValueError:
        raise InvalidSchemaError(
            "unknown permission in route declaration", reason="config"
        ) from None

    async def require_permission(
        request: Request,
        scope: Annotated[IdentityScope, Depends(current_scope)],
        state: Annotated[AuthzState, Depends(get_authz_state)],
    ) -> IdentityScope:
        now = datetime.fromtimestamp(state.clock(), UTC)
        if resource is None:
            if _holds_anywhere(scope, perm, now) is not True:
                raise await _denial(state, request, scope, perm, None, "permission_missing")
            return scope
        try:
            target = _resolve(resource, request, scope)
        except ForbiddenError as exc:
            raise await _denial(
                state, request, scope, perm, None, exc.reason or "forbidden"
            ) from exc
        if target is None:
            raise await _denial(state, request, scope, perm, None, "target_unresolved")
        allowed = permits(
            scope, perm, now=now, domain_id=target.domain_id, resource_id=target.resource_id
        )
        if allowed is not True:
            raise await _denial(state, request, scope, perm, target, "target_out_of_scope")
        return scope

    setattr(require_permission, PERMISSION_MARKER, perm)
    require_permission.__name__ = f"require_{perm.value.replace('.', '_')}"
    return require_permission


def _resolve(
    resolver: ResourceResolver, request: Request, scope: IdentityScope
) -> AuthzTarget | None:
    try:
        target = resolver(request, scope)
    except NeuroSphereError:
        raise
    except Exception as exc:
        raise ForbiddenError(
            "authorization target could not be resolved", reason="target_unresolved"
        ) from exc
    if target is not None and not isinstance(target, AuthzTarget):
        raise ForbiddenError(
            "authorization target could not be resolved", reason="target_unresolved"
        )
    return target


def _holds_anywhere(scope: IdentityScope, perm: Permission, now: datetime) -> bool:
    if domains_with_permission(scope, perm, now=now):
        return True
    return any(
        permits(scope, perm, now=now, resource_id=grant.resource_id.root)
        for grant in scope.to_contract().allowed_resources
    )


async def _denial(
    state: AuthzState,
    request: Request,
    scope: IdentityScope,
    perm: Permission,
    target: AuthzTarget | None,
    reason: str,
) -> ForbiddenError:
    """Record the denied attempt (if a recorder is installed) and return the 403 to raise."""
    recorder = state.denial_recorder
    if recorder is not None:
        attempt = DeniedAttempt(
            scope=scope,
            permission=perm.value,
            reason=reason,
            method=request.method,
            path=request.url.path,
            domain_id=target.domain_id if target else None,
            resource_id=target.resource_id if target else None,
        )
        try:
            await recorder.record_denial(attempt)
        except Exception as exc:
            if request.method.upper() not in SAFE_METHODS:
                raise DependencyTransientError(
                    "audit write failed", reason="audit_write_failed"
                ) from exc
            _LOG.warning(
                "denied-attempt audit record failed",
                extra={"permission": perm.value, "deny_reason": reason},
            )
    return ForbiddenError("insufficient scope for this operation", reason=reason)
