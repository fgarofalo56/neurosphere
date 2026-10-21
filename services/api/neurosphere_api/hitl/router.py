"""Review queue routes (PRP-17 item 4), mounted at ``/api/v1/review``.

| Method | Path                                             | Route permission | Per kind |
|--------|--------------------------------------------------|------------------|----------|
| GET    | ``/domains/{domain}/items``                      | ``data.read``    | filtered |
| GET    | ``/domains/{domain}/items/{item_id}``            | ``data.read``    | 403      |
| POST   | ``/domains/{domain}/items/{item_id}/assignment`` | ``data.read``    | 403      |
| POST   | ``/domains/{domain}/items/{item_id}/decisions``  | ``data.read``    | 403      |

Per kind: ``maker_checker`` needs ``action.approve`` on the domain, insight kinds need
``catalog.curate``; ``HitlService`` rechecks the reviewer against the current policy store. A
``maker_checker`` decision runs the same approval function as the action route. The path
``{domain}`` is the authorization TARGET (403 outside the scope, 503 on a policy-store outage).

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from datetime import UTC, datetime
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Path, Query, Request
from neurosphere_core.auth.scope import Permission
from neurosphere_core.hitl import ReviewKind, ReviewStateName
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

from neurosphere_api.actions.common import audit_correlation_id
from neurosphere_api.actions.dependencies import ActionPlane, get_action_plane
from neurosphere_api.authz import AuthzState, domain_from_path, get_authz_state, require
from neurosphere_api.hitl.models import (
    AssignmentBody,
    ReviewDecisionBody,
    ReviewItemList,
    ReviewItemView,
)
from neurosphere_api.hitl.service import ReviewQueueApi
from neurosphere_api.middleware import correlation_id_of
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "build_router", "register"]

PREFIX: Final = "/api/v1/review"

ReadScope = Annotated[
    IdentityScope, Depends(require(Permission.DATA_READ, domain_from_path("domain")))
]
Plane = Annotated[ActionPlane, Depends(get_action_plane)]
Authz = Annotated[AuthzState, Depends(get_authz_state)]
DomainPath = Annotated[str, Path(min_length=1, max_length=512)]
ItemPath = Annotated[
    str, Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]


def _queue(plane: ActionPlane, scope: IdentityScope, authz: AuthzState) -> ReviewQueueApi:
    return ReviewQueueApi(plane, scope, datetime.fromtimestamp(authz.clock(), UTC))


def _correlation(request: Request) -> str:
    return audit_correlation_id(correlation_id_of(request.scope))


def build_router() -> APIRouter:
    router = APIRouter(tags=["review"])

    @router.get("/domains/{domain}/items", response_model=ReviewItemList)
    async def list_items(
        domain: DomainPath,
        scope: ReadScope,
        plane: Plane,
        authz: Authz,
        kind: Annotated[ReviewKind | None, Query()] = None,
        state: Annotated[ReviewStateName | None, Query()] = None,
        cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    ) -> ReviewItemList:
        return await _queue(plane, scope, authz).list(
            domain, kind=kind, state=state, cursor=cursor, limit=limit
        )

    @router.get("/domains/{domain}/items/{item_id}", response_model=ReviewItemView)
    async def get_item(
        domain: DomainPath, item_id: ItemPath, scope: ReadScope, plane: Plane, authz: Authz
    ) -> ReviewItemView:
        return await _queue(plane, scope, authz).get(domain, item_id)

    @router.post("/domains/{domain}/items/{item_id}/assignment", response_model=ReviewItemView)
    async def assign_item(
        request: Request,
        domain: DomainPath,
        item_id: ItemPath,
        body: AssignmentBody,
        scope: ReadScope,
        plane: Plane,
        authz: Authz,
    ) -> ReviewItemView:
        return await _queue(plane, scope, authz).assign(
            domain, item_id, body, _correlation(request)
        )

    @router.post("/domains/{domain}/items/{item_id}/decisions", response_model=ReviewItemView)
    async def decide_item(
        request: Request,
        domain: DomainPath,
        item_id: ItemPath,
        body: ReviewDecisionBody,
        scope: ReadScope,
        plane: Plane,
        authz: Authz,
    ) -> ReviewItemView:
        return await _queue(plane, scope, authz).decide(
            domain, item_id, body, _correlation(request)
        )

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
