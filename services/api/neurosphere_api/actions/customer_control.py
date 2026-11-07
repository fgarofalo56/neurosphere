"""Customer-level authorization for the execution kill switch (PRP-17 audit close-out).

The kill switch (``PUT /api/v1/actions/emergency-disable``) acts on the WHOLE customer, so
holding ``config.manage`` in some domain is not enough: a single-domain admin must not be able to
re-enable execution customer-wide.

The permission model has no customer-wide role: every role assignment names explicit domains and
there is no wildcard, superuser or bypass (``neurosphere_core.auth.scope.permissions``, PRP-06
C7), and ``neurosphere_api.authz`` has no customer-level primitive. Customer-level control is
therefore modelled as ``config.manage`` on ONE reserved control domain per customer:

    ``<cloud>:<customer>:neurosphere:domain:customer-control``

An operator grants it like any other domain role (membership plus a time-bound ``admin``
assignment in the principal's policy document), so it is explicit, audited in the policy store,
time-bound (``admin`` is privileged, C7) and revocable, and it inherits every derivation rule
(cloud and customer binding, expiry, revocation). A policy naming another customer's or another
cloud's control domain is clipped by derivation, so it never matches.

Order of checks on the route:

1. :func:`~neurosphere_api.authz.require` ``config.manage`` (any domain): 401 / 403
   ``permission_missing`` / 503 on a policy-store outage, exactly as before. The route inventory
   still sees ``config.manage`` through this dependency.
2. :func:`~neurosphere_core.auth.scope.permits` ``config.manage`` on the control domain; a miss is
   403 ``forbidden`` reason ``customer_scope_required``, recorded through the configured denial
   recorder like every other denial (a recorder failure on this mutating route is 503
   ``audit_write_failed``, never an allow).

Disabling and re-enabling use the same route, hence the same check.
"""

# No ``from __future__ import annotations``: FastAPI inspects these signatures, and the
# dependency below closes over a local (``base``) in its annotation.

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated, Final

from fastapi import Depends, Request
from neurosphere_core.auth.scope import Permission, permits
from neurosphere_core.errors import DependencyTransientError, ForbiddenError
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import AuthzState, DeniedAttempt, get_authz_state, require
from neurosphere_api.middleware import correlation_id_of

__all__ = [
    "CUSTOMER_CONTROL_DOMAIN_NAME",
    "CUSTOMER_CONTROL_SOURCE",
    "CUSTOMER_SCOPE_REQUIRED",
    "customer_control_domain",
    "require_customer_control",
]

#: Source and id segments of the reserved per-customer control domain.
CUSTOMER_CONTROL_SOURCE: Final = "neurosphere"
CUSTOMER_CONTROL_DOMAIN_NAME: Final = "customer-control"
#: 403 reason when the caller holds the permission only in ordinary domains.
CUSTOMER_SCOPE_REQUIRED: Final = "customer_scope_required"


def customer_control_domain(cloud: str, customer_id: str) -> str:
    """Canonical id of the reserved control domain of ``customer_id`` in ``cloud``."""
    return f"{cloud}:{customer_id}:{CUSTOMER_CONTROL_SOURCE}:domain:{CUSTOMER_CONTROL_DOMAIN_NAME}"


async def _record_denial(
    state: AuthzState, request: Request, scope: IdentityScope, perm: Permission, domain_id: str
) -> None:
    recorder = state.denial_recorder
    if recorder is None:
        return
    attempt = DeniedAttempt(
        scope=scope,
        permission=perm.value,
        reason=CUSTOMER_SCOPE_REQUIRED,
        method=request.method,
        path=request.url.path,
        domain_id=domain_id,
        resource_id=None,
        correlation_id=correlation_id_of(request.scope),
    )
    try:
        await recorder.record_denial(attempt)
    except Exception as exc:
        # Every route using this check mutates: no audit trail, no answer (fail closed).
        raise DependencyTransientError("audit write failed", reason="audit_write_failed") from exc


def require_customer_control(
    permission: Permission = Permission.CONFIG_MANAGE,
) -> Callable[..., Awaitable[IdentityScope]]:
    """Dependency: ``permission`` held on the caller's customer control domain (see module doc)."""
    base = require(permission)

    async def require_customer_level(
        request: Request,
        scope: Annotated[IdentityScope, Depends(base)],
        state: Annotated[AuthzState, Depends(get_authz_state)],
    ) -> IdentityScope:
        now = datetime.fromtimestamp(state.clock(), UTC)
        target = customer_control_domain(str(scope.cloud), scope.customer_id)
        if permits(scope, permission, now=now, domain_id=target) is True:
            return scope
        await _record_denial(state, request, scope, permission, target)
        raise ForbiddenError(
            "this change applies to the whole customer and needs customer-level "
            f"{permission.value}",
            reason=CUSTOMER_SCOPE_REQUIRED,
        )

    require_customer_level.__name__ = f"require_customer_{permission.value.replace('.', '_')}"
    return require_customer_level
