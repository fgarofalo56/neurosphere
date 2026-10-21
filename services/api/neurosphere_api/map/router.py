"""Viewport route (PRP-18 item 2), mounted at ``/api/v1/map``.

| Method | Path                              | Permission    |
|--------|-----------------------------------|---------------|
| GET    | ``/domains/{domain_id}/viewport`` | ``data.read`` |

The path ``{domain_id}`` is the addressed resource and the authorization TARGET: ``require``
checks ``data.read`` on exactly that domain against the scope derived from the bearer token, so a
caller outside the domain gets 403 and a policy-store outage 503. ``customer_id`` comes only from
the derived ``IdentityScope``. ``node_budget`` and ``edge_budget`` can only lower the server
ceilings (2000 nodes; the configured edge ceiling): a larger request is clamped, not rejected.

Nothing is cached in-process, so a revoked or narrowed scope can never be served a wider cached
view; any future cache must be keyed by ``scope_cache_key``.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Path, Query
from neurosphere_core.aggregates import AggregateReader
from neurosphere_core.auth.scope import Permission, PrincipalPseudonymizer
from neurosphere_core.catalog import CatalogRepository, GraphQuery
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import domain_from_path, require
from neurosphere_api.map.dependencies import (
    DEFAULT_EDGE_BUDGET,
    DEFAULT_NODE_BUDGET,
    Clock,
    ViewportLimits,
    get_aggregate_reader,
    get_clock,
    get_graph,
    get_limits,
    get_pseudonymizer,
    get_repository,
)
from neurosphere_api.map.models import ViewportResponse
from neurosphere_api.map.service import build_viewport
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "build_router", "register"]

PREFIX: Final = "/api/v1/map"

ReadScope = Annotated[
    IdentityScope, Depends(require(Permission.DATA_READ, domain_from_path("domain_id")))
]
Graph = Annotated[GraphQuery, Depends(get_graph)]
Repository = Annotated[CatalogRepository, Depends(get_repository)]
Reader = Annotated[AggregateReader, Depends(get_aggregate_reader)]
Pseudonymizer = Annotated[PrincipalPseudonymizer, Depends(get_pseudonymizer)]
Now = Annotated[Clock, Depends(get_clock)]
Limits = Annotated[ViewportLimits, Depends(get_limits)]
DomainPath = Annotated[str, Path(min_length=1, max_length=512)]
ClusterParam = Annotated[str | None, Query(max_length=128)]
CursorParam = Annotated[str | None, Query(max_length=2048)]
# No upper bound on purpose: an oversized request is clamped by the server, never trusted.
NodeBudget = Annotated[int, Query(ge=1)]
EdgeBudget = Annotated[int, Query(ge=1)]


def build_router() -> APIRouter:
    router = APIRouter(tags=["map"])

    @router.get("/domains/{domain_id}/viewport", response_model=ViewportResponse)
    async def get_viewport(
        domain_id: DomainPath,
        scope: ReadScope,
        graph: Graph,
        repository: Repository,
        reader: Reader,
        pseudonymizer: Pseudonymizer,
        clock: Now,
        limits: Limits,
        cluster_id: ClusterParam = None,
        cursor: CursorParam = None,
        node_budget: NodeBudget = DEFAULT_NODE_BUDGET,
        edge_budget: EdgeBudget = DEFAULT_EDGE_BUDGET,
    ) -> ViewportResponse:
        return await build_viewport(
            scope=scope,
            domain_id=domain_id,
            cluster_id=cluster_id,
            cursor=cursor,
            node_budget=node_budget,
            edge_budget=edge_budget,
            repository=repository,
            graph=graph,
            reader=reader,
            pseudonymizer=pseudonymizer,
            clock=clock,
            limits=limits,
        )

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
