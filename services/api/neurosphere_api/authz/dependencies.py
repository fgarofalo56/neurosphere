"""FastAPI authorization dependencies: ``current_scope`` and ``require`` (PRP-06 item 3).

``current_scope`` reads exactly one request input, the ``Authorization`` header, and passes it
to the item 1 validator; the resulting ``VerifiedClaims`` go to the item 2 deriver, which reads
only claims and the policy store. Headers other than ``Authorization``, query strings, bodies,
cookies and path parameters never reach scope derivation. FastAPI caches the dependency per
request, so a route with several ``require`` dependencies derives the scope once.

Outcomes are exactly three, all through ``neurosphere_core.errors``:

* ``unauthorized`` (401): missing, malformed, ambiguous or invalid token (item 1 reasons).
* ``forbidden`` (403): the derived scope lacks the permission on the target, or the principal is
  revoked. Reasons: ``permission_missing``, ``target_out_of_scope``, ``target_unresolved``, and
  ``role_not_held`` for a role-gated route (:func:`require_role`, PRP-48 item 1). The detail
  names what was missing ("this operation needs `<permission>`", PRP-138 clarification 15).
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
from typing import Annotated, Final, Protocol, runtime_checkable

from fastapi import Depends, Request
from neurosphere_core.admission import TokenBucketLimiter, derive_limiter_key
from neurosphere_core.auth.jwt import VerifiedClaims
from neurosphere_core.auth.scope import (
    Permission,
    Role,
    ScopeDerivation,
    domains_with_permission,
    permits,
)
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    NeuroSphereError,
    NotFoundError,
    UnauthorizedError,
)
from neurosphere_core.observability import get_logger
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz.claim_audit import claim_mapping_stats
from neurosphere_api.authz.recorder import SAFE_METHODS, DeniedAttempt
from neurosphere_api.authz.state import AuthzState, get_authz_state
from neurosphere_api.middleware import correlation_id_of

__all__ = [
    "AUTHENTICATED_MARKER",
    "GROUPS_OVERAGE_ATTRIBUTE",
    "PERMISSION_MARKER",
    "PRESCOPE_AUDIT_ATTRIBUTE",
    "ROLE_MARKER",
    "ROLE_NOT_HELD",
    "AuthzTarget",
    "PermissionDependency",
    "PrescopeAudit",
    "ResourceResolver",
    "RoleResolver",
    "current_derivation",
    "current_scope",
    "domain_from_path",
    "groups_overage_of",
    "holds_role",
    "require",
    "require_authenticated",
    "require_role",
    "resource_from_path",
]

#: Attribute set on every dependency built by :func:`require`; the route inventory reads it.
PERMISSION_MARKER: Final = "__ns_permission__"
#: Attribute set on every dependency built by :func:`require_role` (role-gated route category,
#: ``authz.routes.ROLE_GATED_PATHS``); the route inventory reads it.
ROLE_MARKER: Final = "__ns_role_gate__"
#: 403 reason of a role-gated route whose caller holds no in-scope assignment of the role.
ROLE_NOT_HELD: Final = "role_not_held"
#: Attribute set on the dependency built by :func:`require_authenticated` (authenticated-self
#: route category, ``authz.routes.AUTHENTICATED_SELF_PATHS``); the route inventory reads it.
AUTHENTICATED_MARKER: Final = "__ns_authenticated_self__"
#: ``request.state`` attribute holding the verified token's group overage flag (PRP-138), set
#: by :func:`current_derivation` once a scope was derived. Read with :func:`groups_overage_of`.
GROUPS_OVERAGE_ATTRIBUTE: Final = "ns_groups_overage"
#: ``app.state`` attribute of the optional pre-scope audit hook (PRP-40 item 5).
PRESCOPE_AUDIT_ATTRIBUTE: Final = "prescope_audit"

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
#: Maps a request to the backend role a role-gated route requires; ``None`` means "no such
#: role-gated resource" (404). Reads only path parameters, never a role named by the caller.
RoleResolver = Callable[[Request], Role | None]
PermissionDependency = Callable[..., Awaitable[IdentityScope]]


# --------------------------------------------------------------------------- scope


async def current_derivation(
    request: Request, state: Annotated[AuthzState, Depends(get_authz_state)]
) -> ScopeDerivation:
    """Validate the bearer token and derive the scope (with the policy ids used, for audit).

    A failure is reported to the optional pre-scope audit hook (PRP-40 item 5,
    :func:`_audit_prescope`) and then raised unchanged; the hook never alters the outcome.
    """
    claims: VerifiedClaims | None = None
    try:
        authorization = _authorization_header(request)
        async with asyncio.timeout(state.timeout_seconds):
            claims = await state.authenticator.authenticate(authorization)
            derivation = await state.scope_source.derive(claims)
    except _PASSTHROUGH_ERRORS as exc:
        await _audit_prescope(request, claims, exc.code, exc.reason)
        raise
    except TimeoutError as exc:
        await _audit_prescope(request, claims, DependencyTransientError.code, "authz_timeout")
        raise DependencyTransientError("authorization timed out", reason="authz_timeout") from exc
    except Exception as exc:
        # Includes NeuroSphereError subclasses outside the three authz outcomes.
        await _audit_prescope(request, claims, DependencyTransientError.code, "authz_unavailable")
        raise DependencyTransientError(
            "authorization unavailable", reason="authz_unavailable"
        ) from exc
    if not isinstance(derivation, ScopeDerivation) or not isinstance(
        derivation.scope, IdentityScope
    ):
        await _audit_prescope(request, claims, DependencyTransientError.code, "authz_invalid_scope")
        raise DependencyTransientError(
            "scope source returned an invalid scope", reason="authz_invalid_scope"
        )
    overage = getattr(claims, "groups_overage", False) is True
    setattr(request.state, GROUPS_OVERAGE_ATTRIBUTE, overage)
    stats = claim_mapping_stats(request.app.state)
    if stats is not None:
        stats.observe_claims(claims)  # counts only (PRP-138); never raises, never decides
    return derivation


def groups_overage_of(request: Request) -> bool:
    """True when this request's verified token signalled a group overage (PRP-138).

    Only meaningful after :func:`current_derivation` ran for the request; ``False`` otherwise.
    """
    return getattr(request.state, GROUPS_OVERAGE_ATTRIBUTE, False) is True


@runtime_checkable
class PrescopeAudit(Protocol):
    """Hook for failures before a scope exists (PRP-40 item 5; ``neurosphere_api.audit.prescope``).

    Installed as ``app.state.prescope_audit`` by the composition; absent means no pre-scope audit.
    """

    async def identity_failure(
        self, claims: VerifiedClaims, code: str, reason: str | None, correlation_id: str | None
    ) -> None: ...

    async def unauthenticated(self, reason: str | None, correlation_id: str | None) -> None: ...


async def _audit_prescope(
    request: Request, claims: VerifiedClaims | None, code: str, reason: str | None
) -> None:
    """Report a pre-scope failure: identity known -> denial record; 401 -> SIEM signal only.

    Never raises and never changes the outcome: the caller re-raises the original error. Other
    failures with no verified identity (for example a key-infrastructure outage) are not recorded.
    """
    hook = getattr(request.app.state, PRESCOPE_AUDIT_ATTRIBUTE, None)
    if not isinstance(hook, PrescopeAudit):
        return
    correlation_id = correlation_id_of(request.scope)
    try:
        if claims is not None:
            await hook.identity_failure(claims, code, reason, correlation_id)
        elif code == UnauthorizedError.code:
            await hook.unauthenticated(reason, correlation_id)
    except Exception:
        _LOG.warning("pre-scope audit failed", extra={"deny_reason": reason or code})


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
            _admit(request, scope, None)
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
        _admit(request, scope, target.domain_id)
        return scope

    setattr(require_permission, PERMISSION_MARKER, perm)
    require_permission.__name__ = f"require_{perm.value.replace('.', '_')}"
    return require_permission


# --------------------------------------------------------------------------- require_role


def holds_role(scope: IdentityScope, role: Role, now: datetime) -> bool:
    """True when ``scope`` has an unexpired ``role`` assignment naming a domain of its tenancy.

    Derivation already keeps only the assignment domains the principal is a member of and that
    belong to the deployment's cloud and customer, and drops an assignment left with none. This
    re-checks it on the scope itself: a domain counts only when it is a canonical domain id of the
    scope's own cloud and customer, so an assignment naming only another customer's (or cloud's)
    domain never opens a role-gated route (#91).
    """
    prefix = f"{scope.cloud}:{scope.customer_id}:"
    for assignment in scope.to_contract().roles:
        if Role(assignment.role) is not role:
            continue
        expiry = assignment.expires_at
        if expiry is not None and now >= datetime.fromisoformat(expiry.root.replace("Z", "+00:00")):
            continue
        for domain in assignment.domain_ids:
            parts = domain.root.split(":")
            if domain.root.startswith(prefix) and len(parts) == 5 and parts[3] == "domain":
                return True
    return False


def require_role(role: Role | str | RoleResolver) -> PermissionDependency:
    """Dependency factory for the role-gated route category (PRP-48 item 1, #91).

    Some routes are gated by holding a role rather than a permission (no single permission is
    held by every role; the auditor holds no ``data.read``). ``role`` is a fixed backend role or
    a :data:`RoleResolver` reading the route's path. The check is :func:`holds_role` on the
    server-derived scope; a miss is 403 ``role_not_held`` recorded through the denial recorder
    like every other denial (operation ``role.<role>``). A resolver returning ``None`` is 404.

    The dependency carries :data:`ROLE_MARKER`, not :data:`PERMISSION_MARKER`: the route claims
    no permission. Only a path listed in ``authz.routes.ROLE_GATED_PATHS`` is compliant with this
    marker alone, so a role gate cannot silently replace a permission elsewhere.
    """
    fixed: Role | None = None
    if isinstance(role, str):
        try:
            fixed = Role(role)
        except ValueError:
            raise InvalidSchemaError("unknown role in route declaration", reason="config") from None
    resolver: RoleResolver | None = None if isinstance(role, str) else role

    def wanted_role(request: Request) -> Role | None:
        return fixed if resolver is None else resolver(request)

    async def require_held_role(
        request: Request,
        scope: Annotated[IdentityScope, Depends(current_scope)],
        state: Annotated[AuthzState, Depends(get_authz_state)],
    ) -> IdentityScope:
        wanted = wanted_role(request)
        if wanted is None:
            raise NotFoundError("no such role-gated resource")
        now = datetime.fromtimestamp(state.clock(), UTC)
        if holds_role(scope, wanted, now) is not True:
            raise await _denial(state, request, scope, f"role.{wanted.value}", None, ROLE_NOT_HELD)
        _admit(request, scope, None)
        return scope

    setattr(require_held_role, ROLE_MARKER, True)
    return require_held_role


# --------------------------------------------------------------------------- authenticated


def require_authenticated() -> Callable[..., Awaitable[ScopeDerivation]]:
    """Dependency factory for the authenticated-self route category (PRP-138 clarification 14).

    Requires a valid bearer token and a server-derived scope, and NO permission: 401 / 503 exactly
    as :func:`current_derivation`. Returns the caller's own :class:`ScopeDerivation` (with
    ``claim_grants``), so the route can answer from it and nothing else.

    The dependency carries :data:`AUTHENTICATED_MARKER`, not :data:`PERMISSION_MARKER`. Only a GET
    route whose exact path is in ``authz.routes.AUTHENTICATED_SELF_PATHS`` is compliant with this
    marker alone; anywhere else the route inventory fails app boot.
    """

    async def require_authenticated_caller(
        derivation: Annotated[ScopeDerivation, Depends(current_derivation)],
    ) -> ScopeDerivation:
        return derivation

    setattr(require_authenticated_caller, AUTHENTICATED_MARKER, True)
    return require_authenticated_caller


def _admit(request: Request, scope: IdentityScope, route_domain: str | None) -> None:
    """Charge the per-domain admission limiter (PRP-21), once per request, after the permission
    check passed. A no-op when ``app.state.admission`` is absent (admission off).

    The key comes from the server-derived ``scope`` plus ``route_domain``, a domain ``permits``
    has already validated for this caller; ``derive_limiter_key`` re-checks it against the
    scope's allowed domains. Raises ``RateLimitedError`` (429 with ``Retry-After``). The limiter
    call is synchronous and never awaits.
    """
    limiter = getattr(request.app.state, "admission", None)
    if not isinstance(limiter, TokenBucketLimiter):
        return
    if getattr(request.state, "ns_admitted", False):
        return
    limiter.admit(derive_limiter_key(scope, route_domain))
    request.state.ns_admitted = True


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
    perm: Permission | str,
    target: AuthzTarget | None,
    reason: str,
) -> ForbiddenError:
    """Record the denied attempt (if a recorder is installed) and return the 403 to raise.

    ``perm`` is the permission checked, or the ``role.<role>`` operation of a role gate.
    """
    operation = perm.value if isinstance(perm, Permission) else perm
    recorder = state.denial_recorder
    if recorder is not None:
        attempt = DeniedAttempt(
            scope=scope,
            permission=operation,
            reason=reason,
            method=request.method,
            path=request.url.path,
            domain_id=target.domain_id if target else None,
            resource_id=target.resource_id if target else None,
            correlation_id=correlation_id_of(request.scope),
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
                extra={"permission": operation, "deny_reason": reason},
            )
    return ForbiddenError(f"this operation needs `{operation}`", reason=reason)
