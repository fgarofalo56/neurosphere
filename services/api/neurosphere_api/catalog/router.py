"""Catalog routes (PRP-10 item 5), mounted at ``/api/v1/catalog`` (deprecated alias ``/catalog``
for one release, PRP-29 item 4).

| Method | Path                                        | Permission         |
|--------|---------------------------------------------|--------------------|
| GET    | ``/entities``                               | ``data.read``      |
| POST   | ``/entities``                               | ``catalog.curate`` |
| GET    | ``/entities/{entity_id}``                   | ``data.read``      |
| PUT    | ``/entities/{entity_id}`` (``If-Match``)    | ``catalog.curate`` |
| POST   | ``/entities/{entity_id}/deprecate``         | ``catalog.curate`` |
| POST   | ``/entities/{entity_id}/recertify``         | ``catalog.curate`` |
| POST   | ``/search``                                 | ``data.read``      |
| POST   | ``/lineage/neighbors``                      | ``data.read``      |
| POST   | ``/lineage/impact``                         | ``data.read``      |
| POST   | ``/import``                                 | ``catalog.curate`` |
| GET    | ``/export``                                 | ``data.export``    |
| GET    | ``/recertifications``                       | ``data.read``      |
| POST   | ``/reconcile/stale-agents/dry-run``         | ``catalog.curate`` |
| POST   | ``/reconcile/stale-agents/confirm``         | ``catalog.curate`` |

``entity_id`` is a canonical ID (colons, possibly slashes) so it is a ``path`` parameter, and the
suffix routes are declared before the bare one. Nothing here can match ``<prefix>/curation/...``:
every path starts with a fixed segment other than ``curation``, and there is no catch-all
directly under the prefix.

Authorization:

* Routes on one stored entity check the permission on the STORED entity's domain (see
  ``dependencies.entity_access``); the domain a body or query claims is never used.
* Collection routes (list, search, lineage, export, recertifications, import, reconcile) require
  the permission on at least one domain and then filter by the derived scope: reads by the
  caller's readable domains, export by the ``data.export`` domains, writes by the
  ``catalog.curate`` domains (checked per item in the service). Hidden navigation is not
  authorization: lineage, search and export results are scope-filtered server-side.

Concurrency: every change needs ``If-Match`` (a missing header is ``invalid_schema``, a stale one
``stale_version``); reads return the current ``ETag``. Callers never send query text: filters are
structured and allowlisted and budgets are clamped to server ceilings.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Body, Depends, Header, Query, Request, Response, status
from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_core.auth.scope import Permission
from neurosphere_core.catalog import (
    CatalogEntity,
    GraphQuery,
    GraphResult,
    GraphSearchRequest,
    ImpactRequest,
    NeighborsRequest,
)
from neurosphere_core.catalog.protocol import (
    CanonicalIdStr,
    CatalogRepository,
    EntityFilter,
    EntityTypeName,
    LifecycleName,
)
from neurosphere_core.paging import Page, PageRequest
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import require
from neurosphere_api.catalog.curation.router import audit_correlation_id
from neurosphere_api.catalog.dependencies import (
    EntityAccess,
    entity_access,
    get_graph,
    get_repository,
    get_service,
)
from neurosphere_api.catalog.grant_publish import add_routes as add_grant_publish_routes
from neurosphere_api.catalog.mcp_publish import MCP_PUBLISH_PREFIX, build_mcp_publish_router
from neurosphere_api.catalog.models import (
    ExportPage,
    ImportRequest,
    ImportResult,
    LineageImpactRequest,
    LineageNeighborsRequest,
    RecertificationPage,
    RecertifyRequest,
    StaleAgentConfirm,
    StaleAgentOutcome,
    StaleAgentPlan,
    StaleAgentRequest,
)
from neurosphere_api.catalog.service import CatalogService
from neurosphere_api.deprecation import register_with_alias
from neurosphere_api.middleware import correlation_id_of
from neurosphere_api.routers import RouterRegistry

__all__ = [
    "ALIAS_PREFIX",
    "MAX_LIMIT",
    "MAX_TIMEOUT_MS",
    "PREFIX",
    "build_router",
    "clamp_budget",
    "register",
]

PREFIX = "/api/v1/catalog"
#: Deprecated alias for one release (PRP-29 item 4): same router, same permissions.
ALIAS_PREFIX = "/catalog"
MAX_TIMEOUT_MS: Final = 10_000
MAX_LIMIT: Final = 500

ReadAccess = Annotated[EntityAccess, Depends(entity_access(Permission.DATA_READ))]
CurateAccess = Annotated[EntityAccess, Depends(entity_access(Permission.CATALOG_CURATE))]
ReadScope = Annotated[IdentityScope, Depends(require(Permission.DATA_READ))]
CurateScope = Annotated[IdentityScope, Depends(require(Permission.CATALOG_CURATE))]
ExportScope = Annotated[IdentityScope, Depends(require(Permission.DATA_EXPORT))]
Service = Annotated[CatalogService, Depends(get_service)]
Graph = Annotated[GraphQuery, Depends(get_graph)]
Repository = Annotated[CatalogRepository, Depends(get_repository)]
IfMatch = Annotated[str, Header(alias="If-Match", min_length=1, max_length=300)]
PageSize = Annotated[int, Query(ge=1, le=500)]
CursorParam = Annotated[str | None, Query(max_length=2048)]
EntityTypes = Annotated[list[EntityTypeName] | None, Query(max_length=14)]
DomainIds = Annotated[list[CanonicalIdStr] | None, Query(max_length=100)]
Lifecycles = Annotated[list[LifecycleName] | None, Query(max_length=4)]
EntityBody = Annotated[dict[str, Any], Body()]


def clamp_budget(budget: Budget) -> Budget:
    """Lower (never raise) the caller's budget to the server ceilings."""
    return budget.model_copy(
        update={
            "timeout_ms": min(budget.timeout_ms, MAX_TIMEOUT_MS),
            "limit": min(budget.limit, MAX_LIMIT),
        }
    )


def _quoted(etag: str) -> str:
    return etag if etag.startswith('"') else f'"{etag}"'


def expected_etag(header: str, stored: str) -> str:
    """The ETag to write against: the header value, matched to the stored form (quoted or not).

    A header that names a different version is passed through unchanged so the repository
    refuses it with ``stale_version``.
    """
    value = header.strip().removeprefix("W/")
    for candidate in (value, _quoted(value), value.strip('"')):
        if candidate == stored:
            return stored
    return value


def _correlation(request: Request) -> str:
    return audit_correlation_id(correlation_id_of(request.scope))


def build_router() -> APIRouter:
    router = APIRouter(tags=["catalog"])
    add_grant_publish_routes(router)  # PRP-34 item 5

    # ------------------------------------------------------------------ entities

    @router.get("/entities", response_model=Page[CatalogEntity])
    async def list_entities(
        scope: ReadScope,
        repository: Repository,
        entity_type: EntityTypes = None,
        domain_id: DomainIds = None,
        lifecycle: Lifecycles = None,
        page_size: PageSize = 50,
        cursor: CursorParam = None,
    ) -> Page[CatalogEntity]:
        flt = EntityFilter(
            entity_types=entity_type, domain_ids=domain_id, lifecycle_statuses=lifecycle
        )
        return await repository.list_entities(
            scope, flt, PageRequest(page_size=page_size, cursor=cursor)
        )

    @router.post("/entities", response_model=CatalogEntity, status_code=status.HTTP_201_CREATED)
    async def create_entity(
        request: Request,
        response: Response,
        body: EntityBody,
        scope: CurateScope,
        service: Service,
    ) -> CatalogEntity:
        entity = await service.create(scope, body, correlation_id=_correlation(request))
        response.headers["ETag"] = _quoted(entity.etag.root)
        return entity

    @router.post("/entities/{entity_id:path}/deprecate", response_model=CatalogEntity)
    async def deprecate_entity(
        request: Request,
        response: Response,
        if_match: IfMatch,
        access: CurateAccess,
        service: Service,
    ) -> CatalogEntity:
        entity = await service.deprecate(
            access.scope,
            access.entity,
            expected_etag(if_match, access.entity.etag.root),
            correlation_id=_correlation(request),
        )
        response.headers["ETag"] = _quoted(entity.etag.root)
        return entity

    @router.post("/entities/{entity_id:path}/recertify", response_model=CatalogEntity)
    async def recertify_owner(
        request: Request,
        response: Response,
        body: RecertifyRequest,
        if_match: IfMatch,
        access: CurateAccess,
        service: Service,
    ) -> CatalogEntity:
        entity = await service.recertify(
            access.scope,
            access.entity,
            body.valid_for_days,
            expected_etag(if_match, access.entity.etag.root),
            correlation_id=_correlation(request),
        )
        response.headers["ETag"] = _quoted(entity.etag.root)
        return entity

    @router.put("/entities/{entity_id:path}", response_model=CatalogEntity)
    async def update_entity(
        request: Request,
        response: Response,
        body: EntityBody,
        if_match: IfMatch,
        access: CurateAccess,
        service: Service,
    ) -> CatalogEntity:
        entity = await service.update(
            access.scope,
            access.entity,
            body,
            expected_etag(if_match, access.entity.etag.root),
            correlation_id=_correlation(request),
        )
        response.headers["ETag"] = _quoted(entity.etag.root)
        return entity

    @router.get("/entities/{entity_id:path}", response_model=CatalogEntity)
    async def get_entity(response: Response, access: ReadAccess) -> CatalogEntity:
        response.headers["ETag"] = _quoted(access.entity.etag.root)
        return access.entity

    # ------------------------------------------------------------------ search / lineage

    @router.post("/search", response_model=GraphResult)
    async def search(body: GraphSearchRequest, scope: ReadScope, graph: Graph) -> GraphResult:
        request = body.model_copy(update={"budget": clamp_budget(body.budget)})
        return await graph.search(scope, request)

    @router.post("/lineage/neighbors", response_model=GraphResult)
    async def neighbors(
        body: LineageNeighborsRequest, scope: ReadScope, graph: Graph
    ) -> GraphResult:
        request = NeighborsRequest(
            node_id=body.node_id,
            direction=body.direction,
            filters=body.filters,
            budget=clamp_budget(body.budget),
            view="presented",
        )
        return await graph.neighbors(scope, request)

    @router.post("/lineage/impact", response_model=GraphResult)
    async def impact(body: LineageImpactRequest, scope: ReadScope, graph: Graph) -> GraphResult:
        request = ImpactRequest(
            node_id=body.node_id,
            direction=body.direction,
            filters=body.filters,
            budget=clamp_budget(body.budget),
            view="presented",
        )
        return await graph.impact_paths(scope, request)

    # ------------------------------------------------------------------ import / export

    @router.post("/import", response_model=ImportResult)
    async def import_entities(
        request: Request,
        response: Response,
        body: ImportRequest,
        scope: CurateScope,
        service: Service,
    ) -> ImportResult:
        result = await service.import_entities(scope, body, correlation_id=_correlation(request))
        if not result.dry_run and not result.committed:
            rejected = any(i.status == "rejected" for i in result.items)
            response.status_code = (
                status.HTTP_422_UNPROCESSABLE_CONTENT if rejected else status.HTTP_409_CONFLICT
            )
        return result

    @router.get("/export", response_model=ExportPage)
    async def export(
        scope: ExportScope,
        service: Service,
        entity_type: EntityTypes = None,
        domain_id: DomainIds = None,
        lifecycle: Lifecycles = None,
        page_size: PageSize = 100,
        cursor: CursorParam = None,
    ) -> ExportPage:
        flt = EntityFilter(
            entity_types=entity_type, domain_ids=domain_id, lifecycle_statuses=lifecycle
        )
        return await service.export_page(
            scope, flt, PageRequest(page_size=page_size, cursor=cursor)
        )

    # ------------------------------------------------------------------ governance

    @router.get("/recertifications", response_model=RecertificationPage)
    async def recertifications(
        scope: ReadScope,
        service: Service,
        within_days: Annotated[int, Query(ge=0, le=365)] = 30,
        include: Literal["due", "overdue", "both"] = "both",
        page_size: PageSize = 100,
        cursor: CursorParam = None,
    ) -> RecertificationPage:
        return await service.due_recertifications(
            scope,
            within_days=within_days,
            include=include,
            page=PageRequest(page_size=page_size, cursor=cursor),
        )

    @router.post("/reconcile/stale-agents/dry-run", response_model=StaleAgentPlan)
    async def stale_dry_run(
        body: StaleAgentRequest, scope: CurateScope, service: Service
    ) -> StaleAgentPlan:
        return await service.stale_plan(scope, body.window_days)

    @router.post("/reconcile/stale-agents/confirm", response_model=StaleAgentOutcome)
    async def stale_confirm(
        request: Request, body: StaleAgentConfirm, scope: CurateScope, service: Service
    ) -> StaleAgentOutcome:
        return await service.stale_confirm(scope, body, correlation_id=_correlation(request))

    return router


def register(registry: RouterRegistry) -> None:
    register_with_alias(registry, build_router(), prefix=PREFIX, alias_prefix=ALIAS_PREFIX)
    # PRP-34 item 6: MCP server publish/unpublish drafts (own prefix; no deprecated alias).
    registry.register(MCP_PUBLISH_PREFIX, build_mcp_publish_router())
