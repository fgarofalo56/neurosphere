"""Catalog curation routes (PRP-10 item 4), mounted at ``/catalog/curation``.

| Method | Path                                  | Permission      |
|--------|---------------------------------------|-----------------|
| POST   | ``/edges/{edge_id}/decisions``        | ``catalog.curate`` |
| GET    | ``/edges/{edge_id}/overrides``        | ``data.read``   |
| GET    | ``/edges/{edge_id}/observations``     | ``evidence.read`` (Auditor) |
| GET    | ``/edges/{edge_id}``                  | ``data.read``   |

``edge_id`` is a canonical ID (it contains colons and may contain slashes), so it is a ``path``
parameter. The permission is checked on the domain of the STORED edge (loaded with the caller's
scope; missing and out-of-scope edges both answer 403).

Observations carry raw security evidence and are Auditor-only. Auditors hold no ``data.read``, so
their scope has no readable domains and ``get_edge`` cannot resolve the edge for them. That route
therefore requires ``evidence.read`` on at least one domain and leaves the per-domain decision to
``CatalogRepository.list_observations``, which by protocol raises ``ForbiddenError`` unless the
scope holds ``security_auditor`` for the edge's own domain.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, status
from neurosphere_contracts.catalog.v1.edge_override import EdgeOverride
from neurosphere_core.auth.scope import Permission
from neurosphere_core.catalog import CatalogRepository, EdgeObservation, PresentedEdge
from neurosphere_core.paging import Page, PageRequest
from neurosphere_core.scope import IdentityScope
from pydantic import BaseModel, ConfigDict

from neurosphere_api.authz import require
from neurosphere_api.catalog.curation.dependencies import (
    EdgeAccess,
    edge_access,
    get_repository,
    get_service,
)
from neurosphere_api.catalog.curation.service import CurationService, DecisionResult
from neurosphere_api.middleware import correlation_id_of
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "build_router", "register"]

PREFIX = "/catalog/curation"


def audit_correlation_id(request_id: str) -> str:
    """Request correlation id in audit-safe form: the content guard rejects GUID-shaped values
    outside server-assigned fields, so the dashes are dropped (still joinable to the response)."""
    return "corr-" + request_id.replace("-", "")


CurateAccess = Annotated[EdgeAccess, Depends(edge_access(Permission.CATALOG_CURATE))]
ReadAccess = Annotated[EdgeAccess, Depends(edge_access(Permission.DATA_READ))]
AuditorScope = Annotated[IdentityScope, Depends(require(Permission.EVIDENCE_READ))]
Service = Annotated[CurationService, Depends(get_service)]
Repository = Annotated[CatalogRepository, Depends(get_repository)]


class OverrideHistory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_id: str
    overrides: list[EdgeOverride]


def build_router() -> APIRouter:
    router = APIRouter(tags=["catalog-curation"])

    @router.post(
        "/edges/{edge_id:path}/decisions",
        response_model=DecisionResult,
        status_code=status.HTTP_201_CREATED,
    )
    async def decide(
        request: Request, body: EdgeOverride, access: CurateAccess, service: Service
    ) -> DecisionResult:
        return await service.decide(
            access.scope,
            access.edge,
            body,
            correlation_id=audit_correlation_id(correlation_id_of(request.scope)),
        )

    @router.get("/edges/{edge_id:path}/overrides", response_model=OverrideHistory)
    async def overrides(access: ReadAccess, service: Service) -> OverrideHistory:
        history = await service.overrides(access.scope, access.edge.id)
        return OverrideHistory(edge_id=access.edge.id, overrides=list(history))

    @router.get("/edges/{edge_id:path}/observations", response_model=Page[EdgeObservation])
    async def observations(
        edge_id: Annotated[str, Path(max_length=512)],
        scope: AuditorScope,
        repository: Repository,
        page_size: Annotated[int, Query(ge=1, le=500)] = 50,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
    ) -> Page[EdgeObservation]:
        return await repository.list_observations(
            scope, edge_id, PageRequest(page_size=page_size, cursor=cursor)
        )

    @router.get("/edges/{edge_id:path}", response_model=PresentedEdge)
    async def presented(access: ReadAccess, service: Service) -> PresentedEdge:
        return await service.presented(access.scope, access.edge)

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
