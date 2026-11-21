"""Providers and small helpers of the catalog access routes (PRP-73 item 3).

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated

from fastapi import Depends
from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_core.catalog import CatalogRepository, GraphQuery
from neurosphere_core.catalog.graph.access import AccessBudget, AccessEngine
from neurosphere_core.catalog.graph.region_groups import normalise_regions

from neurosphere_api.catalog.access.models import AccessBudgetIn
from neurosphere_api.catalog.dependencies import get_graph, get_repository
from neurosphere_api.catalog.router import MAX_LIMIT, MAX_TIMEOUT_MS, clamp_budget

__all__ = ["get_access_engine", "to_access_budget", "validate_regions"]


def get_access_engine(
    repository: Annotated[CatalogRepository, Depends(get_repository)],
    graph: Annotated[GraphQuery, Depends(get_graph)],
) -> AccessEngine:
    """The engine over the catalog's repository and graph (tests override either provider)."""
    return AccessEngine(repository, graph)


def validate_regions(regions: list[str] | None, cloud: str) -> None:
    """The ONE place the API checks explicit residency regions: a thin call into the core.

    The core decides whether each region is a known region of ``cloud`` (``AccessQueryError``,
    reason ``unknown_region``). Applies to the request filter only.
    """
    if regions:
        normalise_regions(list(regions), cloud)


def to_access_budget(budget: AccessBudgetIn | None) -> AccessBudget | None:
    """Lower the request budget to the server ceilings; a missing budget keeps the engine's own.

    The time and row ceilings go through the catalog's shared ``clamp_budget`` (so the lineage
    and access routes cannot drift); the engine applies its own fixed ceilings again.
    """
    if budget is None:
        return None
    clamped = clamp_budget(
        Budget(
            timeout_ms=budget.timeout_ms or MAX_TIMEOUT_MS,
            limit=budget.max_accessors or MAX_LIMIT,
            max_depth=0,
        )
    )
    return AccessBudget(
        timeout_ms=clamped.timeout_ms if budget.timeout_ms else None,
        max_accessors=clamped.limit if budget.max_accessors else None,
        max_assets=budget.max_assets,
    )
