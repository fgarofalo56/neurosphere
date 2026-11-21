"""Catalog access routes (PRP-73 item 3), mounted at ``/api/v1/catalog/access`` (deprecated alias
``/catalog/access``).

| Method | Path             | Permission  | Audit operation        |
|--------|------------------|-------------|------------------------|
| POST   | ``/query``       | ``data.read`` | ``catalog.access_query`` |
| POST   | ``/dependents``  | ``data.read`` | ``catalog.dependents``   |
| GET    | ``/region-groups`` | ``data.read`` | none (static reference data) |

Scope comes only from the server identity; request bodies have no customer, cloud or domain-scope
field. The allowed-read audit record holds the domains read and the result count, never asset
names, ids, filter values or terms. ``region-groups`` is not audited: it returns a static,
in-repo list that depends only on the caller's cloud and reads no catalog entity, like the
unaudited lineage routes; the audited reads are the ones that scan catalog data. An
``AccessQueryError`` is an ``InvalidSchemaError`` (422) carrying its reason code in ``reason``.
"""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import APIRouter, Depends
from neurosphere_core.auth.scope import Permission
from neurosphere_core.catalog.graph.access import (
    AccessEngine,
    AccessQuery,
    AccessResult,
    AccessRow,
)
from neurosphere_core.catalog.graph.region_groups import load_region_groups
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import require
from neurosphere_api.authz.read_audit import ReadAudit, audited_read
from neurosphere_api.catalog.access.deps import (
    get_access_engine,
    to_access_budget,
    validate_regions,
)
from neurosphere_api.catalog.access.models import (
    AccessAssetView,
    AccessBoundView,
    AccessDependentsRequest,
    AccessDependentsResponse,
    AccessDepthGroup,
    AccessQueryRequest,
    AccessQueryResponse,
    AccessRowView,
    RegionGroupsResponse,
    RegionGroupView,
)
from neurosphere_api.deprecation import register_with_alias
from neurosphere_api.routers import RouterRegistry

__all__ = ["ALIAS_PREFIX", "PREFIX", "build_router", "register"]

PREFIX = "/api/v1/catalog/access"
#: Deprecated alias for one release, like every catalog route.
ALIAS_PREFIX = "/catalog/access"

QueryAudit = Annotated[
    ReadAudit, Depends(audited_read(Permission.DATA_READ, "catalog.access_query"))
]
DependentsAudit = Annotated[
    ReadAudit, Depends(audited_read(Permission.DATA_READ, "catalog.dependents"))
]
ReadScope = Annotated[IdentityScope, Depends(require(Permission.DATA_READ))]
Engine = Annotated[AccessEngine, Depends(get_access_engine)]

_QUERY_DESCRIPTION: Final = (
    "Which in-scope agents and tools read or wrote the selected data assets. Results are observed "
    "edges (who did), not entitlements (who could). An empty sensitivity_categories list or a "
    "null value on an asset means not assessed, never no; such assets are listed under "
    "unassessed_assets only when include_unassessed is true. When region_group and "
    "residency_regions are both given, their regions are unioned. residency_regions values "
    "are validated against the known-region list for the caller's cloud; an unknown region "
    "answers 422 with reason unknown_region. The eu group is a NeuroSphere "
    "classification of Azure region locations and implies nothing about compliance. A truncated "
    "result is partial: truncated_reason says which bound stopped the scan and assets_scanned "
    "how many assets were examined. Scope comes only from the caller's identity; domain_ids "
    "narrows within it. Each call appends one allowed-read audit record holding the domains "
    "read and the result count only."
)
_DEPENDENTS_DESCRIPTION: Final = (
    "Entities that depend on a failing service or tool (blast radius), grouped by distance "
    "(max_depth 1 to 5; any other value answers 422 with a reason code), each with the relation "
    "path. Results are observed or curated edges, not entitlements. A truncated result is "
    "partial: truncated_reason says which bound stopped the walk. Only in-scope entities "
    "appear. Each call appends one allowed-read audit record holding the domains read and the "
    "result count only."
)
_REGION_GROUPS_DESCRIPTION: Final = (
    "Region group names and their member regions for the caller's cloud (the Government cloud "
    "has none). The eu group is a NeuroSphere classification of Azure region locations and "
    "implies nothing about compliance."
)


def _row(row: AccessRow) -> AccessRowView:
    return AccessRowView.model_validate(row.model_dump(mode="json"))


def _bound(result: AccessResult) -> AccessBoundView:
    return AccessBoundView.model_validate(result.bound.model_dump(mode="json"))


def _read_domains(scope: IdentityScope, requested: list[str] | None) -> list[str]:
    """In-scope domains read; requested ids outside the scope were never read, so not recorded."""
    readable = scope.allowed_domains
    return [d for d in requested if d in readable] if requested else list(readable)


def build_router() -> APIRouter:
    router = APIRouter(tags=["catalog"])

    @router.post(
        "/query",
        response_model=AccessQueryResponse,
        summary="Who reads or writes these data assets",
        description=_QUERY_DESCRIPTION,
    )
    async def access_query(
        body: AccessQueryRequest, audit: QueryAudit, engine: Engine
    ) -> AccessQueryResponse:
        validate_regions(body.filters.residency_regions, str(audit.scope.cloud))
        query = AccessQuery(
            asset_ids=body.asset_ids,
            classifications=body.filters.classifications,
            sensitivity_categories=body.filters.sensitivity_categories,
            contains_personal_data=body.filters.contains_personal_data,
            residency_regions=body.filters.residency_regions,
            region_group=body.filters.region_group,
            domain_ids=body.filters.domain_ids,
            modes=body.modes,
            include_unassessed=body.include_unassessed,
            budget=to_access_budget(body.budget),
        )
        result = await engine.who_accesses(audit.scope, query)
        response = AccessQueryResponse(
            rows=[_row(r) for r in result.rows],
            assets=[AccessAssetView.model_validate(a.model_dump()) for a in result.assets],
            unassessed_assets=(
                None
                if result.unassessed_assets is None
                else [
                    AccessAssetView.model_validate(a.model_dump()) for a in result.unassessed_assets
                ]
            ),
            unassessed_count=result.unassessed_count,
            truncated=result.truncated,
            truncated_reason=result.truncated_reason,
            assets_scanned=result.assets_scanned,
            bound=_bound(result),
        )
        await audit.allowed(_read_domains(audit.scope, body.filters.domain_ids), len(result.rows))
        return response

    @router.post(
        "/dependents",
        response_model=AccessDependentsResponse,
        summary="Entities affected when a node fails",
        description=_DEPENDENTS_DESCRIPTION,
    )
    async def dependents(
        body: AccessDependentsRequest, audit: DependentsAudit, engine: Engine
    ) -> AccessDependentsResponse:
        result = await engine.dependents(
            audit.scope, body.node_id, body.max_depth, to_access_budget(body.budget)
        )
        response = AccessDependentsResponse(
            groups=[
                AccessDepthGroup(depth=depth, rows=[_row(r) for r in rows])
                for depth, rows in result.grouped_by_depth().items()
            ],
            total=len(result.rows),
            truncated=result.truncated,
            truncated_reason=result.truncated_reason,
            assets_scanned=result.assets_scanned,
            bound=_bound(result),
        )
        await audit.allowed(_read_domains(audit.scope, None), len(result.rows))
        return response

    @router.get(
        "/region-groups",
        response_model=RegionGroupsResponse,
        summary="Region groups available to the access query",
        description=_REGION_GROUPS_DESCRIPTION,
    )
    async def region_groups(scope: ReadScope) -> RegionGroupsResponse:
        groups = load_region_groups()
        return RegionGroupsResponse(
            groups=[
                RegionGroupView(name=name, regions=sorted(groups.regions_in(scope.cloud, name)))
                for name in groups.group_names(scope.cloud)
            ]
        )

    return router


def register(registry: RouterRegistry) -> None:
    register_with_alias(registry, build_router(), prefix=PREFIX, alias_prefix=ALIAS_PREFIX)
