"""Principal revocation routes under ``/api/v1/admin/identity`` (PRP-39 item 4).

| Method | Path                                      | Permission          |
|--------|-------------------------------------------|---------------------|
| POST   | ``/principals/{principal_id}/revocation`` | ``revocation.manage`` |
| GET    | ``/principals/{principal_id}/revocation`` | ``revocation.manage`` |
| DELETE | ``/principals/{principal_id}/revocation`` | ``revocation.manage`` |

All three go through the ONE composed ``RevocationService`` (``app.state.identity_admin``), so the
shipped authorizer (``revocation.manage`` in any unexpired domain assignment, target in the
actor's own cloud and customer, else 403 ``cross_scope_target``; Clarification 5), the
intent/outcome audit records (chain ``<customer>.identity-admin``) and the fan-out to every cache
invalidator and push-session closer apply exactly as PRP-06 specified.

* ``POST`` with ``mode: issued_before`` denies every token issued at or before the revocation
  (plus clock skew); ``mode: until_lifted`` denies every token until ``DELETE`` lifts it.
* ``DELETE`` (``?reason=``) lifts an ``until_lifted`` block (``principal.revoke_lift``); without
  an active block it is 404 ``no_active_block``. Tokens from before the block stay refused.
* Revocation is bounded by ``NS_REVOCATION_TTL_SECONDS`` (``propagation_bound_seconds``), never
  instant on every replica. A store outage is 503, never "not revoked".

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request, status
from neurosphere_contracts.admin.v1.revocation_request import RevocationRequest
from neurosphere_contracts.admin.v1.revocation_status import RevocationStatus
from neurosphere_core.auth.revocation import RevocationService
from neurosphere_core.auth.scope import Permission
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.scope import IdentityScope

from neurosphere_api.actions.common import audit_correlation_id
from neurosphere_api.admin.identity.models import revocation_status
from neurosphere_api.admin.identity.plane import IdentityAdminPlane, bind_correlation, get_plane
from neurosphere_api.admin.identity.router import PrincipalPath, ReasonQuery
from neurosphere_api.authz import require
from neurosphere_api.middleware import correlation_id_of

__all__ = ["DEFAULT_LIFT_REASON", "build_router"]

DEFAULT_LIFT_REASON: Final = "lifted_by_administrator"

RevocationScope = Annotated[IdentityScope, Depends(require(Permission.REVOCATION_MANAGE))]


def _service(plane: Annotated[IdentityAdminPlane, Depends(get_plane)]) -> RevocationService:
    if plane.revocation is None:
        raise DependencyTransientError(
            "revocation service is not configured", reason="revocation_service_unconfigured"
        )
    return plane.revocation


Service = Annotated[RevocationService, Depends(_service)]


def _bind(request: Request) -> None:
    bind_correlation(audit_correlation_id(correlation_id_of(request.scope)))


def build_router() -> APIRouter:
    router = APIRouter(tags=["admin-identity"])
    path = "/principals/{principal_id}/revocation"

    @router.post(path, response_model=RevocationStatus, status_code=status.HTTP_200_OK)
    async def revoke_principal(
        request: Request,
        principal_id: PrincipalPath,
        body: RevocationRequest,
        scope: RevocationScope,
        service: Service,
    ) -> RevocationStatus:
        _bind(request)
        outcome = await service.revoke(scope, principal_id, reason=body.reason.root, mode=body.mode)
        return revocation_status(
            principal_id,
            outcome.entry,
            propagation_bound_seconds=outcome.propagation_bound_seconds,
        )

    @router.get(path, response_model=RevocationStatus)
    async def get_revocation(
        request: Request, principal_id: PrincipalPath, scope: RevocationScope, service: Service
    ) -> RevocationStatus:
        _bind(request)
        entry = await service.status(scope, principal_id)
        return revocation_status(
            principal_id, entry, propagation_bound_seconds=service.propagation_bound_seconds
        )

    @router.delete(path, response_model=RevocationStatus)
    async def lift_revocation(
        request: Request,
        principal_id: PrincipalPath,
        scope: RevocationScope,
        service: Service,
        reason: ReasonQuery = DEFAULT_LIFT_REASON,
    ) -> RevocationStatus:
        _bind(request)
        outcome = await service.lift(scope, principal_id, reason=reason)
        return revocation_status(
            principal_id,
            outcome.entry,
            propagation_bound_seconds=outcome.propagation_bound_seconds,
        )

    return router
