"""Gateway registry routes, mounted at ``/api/v1/gateways`` (PRP-33 item 6, observe mode).

| Method | Path                                          | Permission      |
|--------|-----------------------------------------------|-----------------|
| POST   | ``/domains/{domain}/gateways``                | ``config.manage`` |
| GET    | ``/domains/{domain}/gateways``                | ``data.read``   |
| GET    | ``/domains/{domain}/gateways/{gateway_id}``   | ``data.read``   |
| GET    | ``/domains/{domain}/gateways/{gateway_id}/inventory`` | ``data.read`` |
| POST   | ``/domains/{domain}/gateways/{gateway_id}/sync`` | ``config.manage`` |

The path ``{domain}`` is the authorization target (403 outside the caller's scope, 503 on a
policy-store outage). There is no ``deploy.*`` permission in the shipped permission set, so the
gateway write routes use ``config.manage`` (the precedent of the discovery scan and the plan
routes) and the read routes ``data.read``. No route writes to the gateway itself.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Path, Query, Request, status
from neurosphere_core.auth.scope import Permission
from neurosphere_core.gateway import GatewayInventory, GatewayRegistration
from neurosphere_core.gateway.models import GATEWAY_ID_PATTERN
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import domain_from_path, require
from neurosphere_api.gateway.dependencies import GatewayPlane, get_gateway_plane
from neurosphere_api.gateway.models import GatewayDetail, GatewayList, RegisterGatewayBody
from neurosphere_api.gateway.service import GatewayApi
from neurosphere_api.middleware import correlation_id_of
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "build_router", "register"]

PREFIX: Final = "/api/v1/gateways"

ReadScope = Annotated[
    IdentityScope, Depends(require(Permission.DATA_READ, domain_from_path("domain")))
]
WriteScope = Annotated[
    IdentityScope, Depends(require(Permission.CONFIG_MANAGE, domain_from_path("domain")))
]
Plane = Annotated[GatewayPlane, Depends(get_gateway_plane)]
DomainPath = Annotated[str, Path(min_length=1, max_length=512)]
GatewayPath = Annotated[str, Path(pattern=GATEWAY_ID_PATTERN)]


def _correlation(request: Request) -> str:
    return "corr-" + correlation_id_of(request.scope).replace("-", "")


def build_router() -> APIRouter:
    router = APIRouter(tags=["gateways"])

    @router.post(
        "/domains/{domain}/gateways",
        response_model=GatewayRegistration,
        status_code=status.HTTP_201_CREATED,
    )
    async def register_gateway(
        request: Request,
        domain: DomainPath,
        body: RegisterGatewayBody,
        scope: WriteScope,
        plane: Plane,
    ) -> GatewayRegistration:
        return await GatewayApi(plane).register(scope, domain, body, _correlation(request))

    @router.get("/domains/{domain}/gateways", response_model=GatewayList)
    async def list_gateways(
        domain: DomainPath,
        scope: ReadScope,
        plane: Plane,
        cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    ) -> GatewayList:
        return await GatewayApi(plane).list(scope, domain, cursor=cursor, limit=limit)

    @router.get("/domains/{domain}/gateways/{gateway_id}", response_model=GatewayDetail)
    async def get_gateway(
        domain: DomainPath, gateway_id: GatewayPath, scope: ReadScope, plane: Plane
    ) -> GatewayDetail:
        return await GatewayApi(plane).detail(scope, domain, gateway_id)

    @router.get(
        "/domains/{domain}/gateways/{gateway_id}/inventory", response_model=GatewayInventory
    )
    async def get_inventory(
        domain: DomainPath, gateway_id: GatewayPath, scope: ReadScope, plane: Plane
    ) -> GatewayInventory:
        return await GatewayApi(plane).inventory(scope, domain, gateway_id)

    @router.post("/domains/{domain}/gateways/{gateway_id}/sync", response_model=GatewayDetail)
    async def sync_gateway(
        request: Request,
        domain: DomainPath,
        gateway_id: GatewayPath,
        scope: WriteScope,
        plane: Plane,
    ) -> GatewayDetail:
        return await GatewayApi(plane).sync(scope, domain, gateway_id, _correlation(request))

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
