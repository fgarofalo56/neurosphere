"""Domain-path catalog reads for the browser (PRP-31 item 2), mounted at
``/api/v1/catalog/domains``.

| Method | Path                    | Permission                    |
|--------|-------------------------|-------------------------------|
| GET    | ``/{domain}/entities``  | ``data.read`` on ``{domain}`` |
| POST   | ``/{domain}/search``    | ``data.read`` on ``{domain}`` |
| GET    | ``/{domain}/export``    | ``data.export`` on ``{domain}`` |

The PRP-10 collection routes take the domain as a ``domain_id`` query key, which the browser
``ApiClient`` refuses to send. These adapters take it from the path instead, check the permission
on exactly that domain, and then call the same repository, graph and service the PRP-10 routes use
with the domain filter fixed to ``[domain]``. Nothing a caller sends can widen the filter: the
repository, graph and export service still filter by the derived scope.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Path, Query
from neurosphere_core.auth.scope import Permission
from neurosphere_core.catalog import CatalogEntity, GraphQuery, GraphResult, GraphSearchRequest
from neurosphere_core.catalog.protocol import (
    CatalogRepository,
    EntityFilter,
    EntityTypeName,
    LifecycleName,
)
from neurosphere_core.paging import Page, PageRequest
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import domain_from_path, require
from neurosphere_api.catalog.dependencies import get_graph, get_repository, get_service
from neurosphere_api.catalog.models import ExportPage
from neurosphere_api.catalog.router import clamp_budget
from neurosphere_api.catalog.service import CatalogService
from neurosphere_api.ui_adapters.models import CatalogDomainSearchRequest

__all__ = ["PREFIX", "DomainPath", "build_router"]

PREFIX: Final = "/api/v1/catalog/domains"

DomainPath = Annotated[str, Path(min_length=1, max_length=512)]
ReadScope = Annotated[
    IdentityScope, Depends(require(Permission.DATA_READ, domain_from_path("domain")))
]
ExportScope = Annotated[
    IdentityScope, Depends(require(Permission.DATA_EXPORT, domain_from_path("domain")))
]
Repository = Annotated[CatalogRepository, Depends(get_repository)]
Graph = Annotated[GraphQuery, Depends(get_graph)]
Service = Annotated[CatalogService, Depends(get_service)]
PageSize = Annotated[int, Query(ge=1, le=500)]
CursorParam = Annotated[str | None, Query(max_length=2048)]
EntityTypes = Annotated[list[EntityTypeName] | None, Query(max_length=14)]
Lifecycles = Annotated[list[LifecycleName] | None, Query(max_length=4)]


def _filter(
    domain: str, entity_type: list[EntityTypeName] | None, lifecycle: list[LifecycleName] | None
) -> EntityFilter:
    return EntityFilter(entity_types=entity_type, domain_ids=[domain], lifecycle_statuses=lifecycle)


def build_router() -> APIRouter:
    router = APIRouter(tags=["ui-adapters"])

    @router.get("/{domain}/entities", response_model=Page[CatalogEntity])
    async def list_domain_entities(
        domain: DomainPath,
        scope: ReadScope,
        repository: Repository,
        entity_type: EntityTypes = None,
        lifecycle: Lifecycles = None,
        page_size: PageSize = 50,
        cursor: CursorParam = None,
    ) -> Page[CatalogEntity]:
        return await repository.list_entities(
            scope,
            _filter(domain, entity_type, lifecycle),
            PageRequest(page_size=page_size, cursor=cursor),
        )

    @router.post("/{domain}/search", response_model=GraphResult)
    async def search_domain(
        domain: DomainPath, body: CatalogDomainSearchRequest, scope: ReadScope, graph: Graph
    ) -> GraphResult:
        request = GraphSearchRequest(
            term=body.term,
            filters=EntityFilter(entity_types=body.entity_types, domain_ids=[domain]),
            budget=clamp_budget(body.budget),
        )
        return await graph.search(scope, request)

    @router.get("/{domain}/export", response_model=ExportPage)
    async def export_domain(
        domain: DomainPath,
        scope: ExportScope,
        service: Service,
        entity_type: EntityTypes = None,
        lifecycle: Lifecycles = None,
        page_size: PageSize = 100,
        cursor: CursorParam = None,
    ) -> ExportPage:
        return await service.export_page(
            scope,
            _filter(domain, entity_type, lifecycle),
            PageRequest(page_size=page_size, cursor=cursor),
        )

    return router
