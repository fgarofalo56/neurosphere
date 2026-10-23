"""Federation routes (PRP-21 item 3), mounted at ``/api/v1/federation``.

| Method | Path             | Permission    | What |
|--------|------------------|---------------|------|
| GET    | ``/summary``       | ``data.read`` | merged, same-cloud same-boundary cells |
| GET    | ``/cell-summary``  | ``data.read`` | this cell only (what peers call) |

Both routes take the caller's scope from the bearer token only (``require`` -> ``current_scope``).
Neither declares a ``domain_id`` or ``customer_id`` parameter, so a spoofed value in the query
string or body is never read. ``/summary`` forwards the caller's own ``Authorization`` header to
each cell; every cell derives the scope itself. The cache is consulted after ``require``, so a
revoked principal is 403 immediately even with a warm cache. A missing federation or aggregate
configuration is 503 (fail closed).

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query, Request
from neurosphere_core.aggregates import AggregateReader
from neurosphere_core.auth.scope import Permission
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.scope import IdentityScope
from neurosphere_workers.federation import MAX_DAYS, CellSummary, compute_cell_summary

from neurosphere_api.authz import require
from neurosphere_api.federation.models import MergedSummary
from neurosphere_api.federation.service import FederationState
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "build_router", "get_federation", "register"]

PREFIX: Final = "/api/v1/federation"

ReadScope = Annotated[IdentityScope, Depends(require(Permission.DATA_READ))]
Days = Annotated[int, Query(ge=1, le=MAX_DAYS)]
CellIds = Annotated[list[str] | None, Query(max_length=20)]


def get_federation(request: Request) -> FederationState:
    state = getattr(request.app.state, "federation", None)
    if not isinstance(state, FederationState):
        raise DependencyTransientError(
            "federation is not configured", reason="federation_unconfigured"
        )
    return state


def _get_reader(request: Request) -> AggregateReader:
    reader = getattr(request.app.state, "aggregate_reader", None)
    if not isinstance(reader, AggregateReader):
        raise DependencyTransientError(
            "aggregate reader is not configured", reason="aggregates_unconfigured"
        )
    return reader


Federation = Annotated[FederationState, Depends(get_federation)]
Reader = Annotated[AggregateReader, Depends(_get_reader)]


def build_router() -> APIRouter:
    router = APIRouter(tags=["federation"])

    @router.get("/summary", response_model=MergedSummary)
    async def merged_summary(
        request: Request,
        scope: ReadScope,
        federation: Federation,
        days: Days = 30,
        cells: CellIds = None,
    ) -> MergedSummary:
        selected = federation.federator.select(cells)
        key = federation.cache_key(scope, days=days, cells=selected)
        cached = federation.cache.get(key)
        if cached is not None:
            return cached
        merged = await federation.federator.summarize(
            scope, request.headers.get("authorization"), days=days, cells=selected
        )
        federation.cache.put(key, merged)
        return merged

    @router.get("/cell-summary", response_model=CellSummary)
    async def cell_summary(
        scope: ReadScope, federation: Federation, reader: Reader, days: Days = 30
    ) -> CellSummary:
        cell = federation.local_cell
        if cell is None:
            raise DependencyTransientError(
                "this deployment is not a registered cell", reason="federation_unconfigured"
            )
        return await compute_cell_summary(reader, scope, cell=cell, days=days)

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
