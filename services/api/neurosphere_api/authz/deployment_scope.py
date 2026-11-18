"""Deployment-scoped (customer-wide) administration dependency (PRP-48 item 3, #114).

Some routes change state that applies to the whole deployment, not to one domain: MCP server
administration, deploy scan and plan, the execution kill switch, connector and producer
configuration, data-lifecycle management. Holding ``config.manage`` in ONE ordinary domain must
not be enough for those, and there is still no customer-wide role, wildcard or bypass (PRP-06 C7).

The deployment-scoped admin is the shape PRP-65 defined in
``neurosphere_core.auth.scope.permissions``: the permission held on the customer's ONE reserved
control domain ``<cloud>:<customer>:neurosphere:domain:customer-control``
(:func:`~neurosphere_core.auth.scope.customer_control_domain_id`), checked with
:func:`~neurosphere_core.auth.scope.permits_customer_wide`. It is granted like any other domain
role (membership plus a time-bound ``admin`` assignment), so it is explicit, expiring, audited in
the policy store and revocable, and derivation clips another cloud's or customer's control domain.
The kill switch already used exactly this domain (operator decision of 2026-11-05), so existing
grants keep working.

Order of checks (:func:`require_deployment_admin`):

1. :func:`~neurosphere_api.authz.require` ``permission`` with no target: 401 / 403
   ``permission_missing`` / 503 exactly as for any route; the route inventory sees the
   permission through this dependency's marker.
2. :func:`~neurosphere_core.auth.scope.permits_customer_wide`: a miss is 403 ``forbidden`` with
   reason :data:`CUSTOMER_SCOPE_REQUIRED`, recorded through the configured denial recorder with
   the control domain as the target. A recorder failure is 503 ``audit_write_failed`` on every
   method (fail closed: these routes administer the deployment), never an allow.

Reason code: PRP-37/PRP-65 and every route shipped since (identity admin, audit export and
denials, connectors, producers, lifecycle) answer ``customer_scope_required``; this module keeps
that one code instead of introducing a second spelling (PRP-48 acceptance #114 allows it).
"""

# No ``from __future__ import annotations``: FastAPI inspects these signatures, and the
# dependency below closes over a local (``base``) in its annotation.

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated, Final

from fastapi import Depends, Request
from neurosphere_core.auth.scope import (
    Permission,
    customer_control_domain_id,
    permits_customer_wide,
)
from neurosphere_core.errors import DependencyTransientError, ForbiddenError
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz.dependencies import require
from neurosphere_api.authz.recorder import DeniedAttempt
from neurosphere_api.authz.state import AuthzState, get_authz_state
from neurosphere_api.middleware import correlation_id_of

__all__ = [
    "CUSTOMER_SCOPE_REQUIRED",
    "DEPLOYMENT_ADMIN_MARKER",
    "require_deployment_admin",
]

#: 403 reason when the caller holds the permission only in ordinary domains.
CUSTOMER_SCOPE_REQUIRED: Final = "customer_scope_required"
#: Attribute set on every dependency built by :func:`require_deployment_admin` (tests and the
#: security suite read it to prove a route is deployment-scoped).
DEPLOYMENT_ADMIN_MARKER: Final = "__ns_deployment_admin__"


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
        # Deployment administration: no audit trail, no answer (fail closed on every method).
        raise DependencyTransientError("audit write failed", reason="audit_write_failed") from exc


def require_deployment_admin(
    permission: Permission = Permission.CONFIG_MANAGE,
) -> Callable[..., Awaitable[IdentityScope]]:
    """Dependency: ``permission`` held on the caller's own control domain (see module doc).

    The target is built from the server-derived scope's cloud and customer, never from request
    input. Resource-scoped grants never confer it; nothing else short-circuits the check.
    """
    perm = Permission(permission)
    base = require(perm)

    async def require_deployment_scope(
        request: Request,
        scope: Annotated[IdentityScope, Depends(base)],
        state: Annotated[AuthzState, Depends(get_authz_state)],
    ) -> IdentityScope:
        now = datetime.fromtimestamp(state.clock(), UTC)
        if permits_customer_wide(scope, perm, now=now) is True:
            return scope
        target = customer_control_domain_id(str(scope.cloud), scope.customer_id)
        await _record_denial(state, request, scope, perm, target)
        raise ForbiddenError(
            f"this operation needs `{perm.value}` on the whole deployment"
            " (the customer control domain)",
            reason=CUSTOMER_SCOPE_REQUIRED,
        )

    setattr(require_deployment_scope, DEPLOYMENT_ADMIN_MARKER, perm)
    require_deployment_scope.__name__ = f"require_deployment_{perm.value.replace('.', '_')}"
    return require_deployment_scope
