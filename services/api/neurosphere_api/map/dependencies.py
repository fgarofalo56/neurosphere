"""FastAPI providers for the viewport API (PRP-18 item 2).

Each reads a collaborator from ``app.state`` and fails closed with 503 when it is unset; tests
use ``app.dependency_overrides``.

* :func:`get_graph` -- ``app.state.catalog_graph`` (a ``GraphQuery``).
* :func:`get_repository` -- ``app.state.catalog_repository`` (a ``CatalogRepository``).
* :func:`get_aggregate_reader` -- ``app.state.aggregate_reader`` (an ``AggregateReader``).
* :func:`get_pseudonymizer` -- ``app.state.map_pseudonymizer`` (a ``PrincipalPseudonymizer``).
* :func:`get_clock` -- UTC now.
* :func:`get_limits` -- optional ``app.state.map_viewport_limits`` (a ``ViewportLimits``).

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from fastapi import Request
from neurosphere_core.aggregates import AggregateReader
from neurosphere_core.auth.scope import PrincipalPseudonymizer
from neurosphere_core.catalog import CatalogRepository, GraphQuery
from neurosphere_core.errors import DependencyTransientError

__all__ = [
    "DEFAULT_EDGE_BUDGET",
    "DEFAULT_NODE_BUDGET",
    "MAX_VIEWPORT_EDGES",
    "MAX_VIEWPORT_NODES",
    "Clock",
    "ViewportLimits",
    "get_aggregate_reader",
    "get_clock",
    "get_graph",
    "get_limits",
    "get_pseudonymizer",
    "get_repository",
]

MAX_VIEWPORT_NODES: Final = 2000
"""Hard server ceiling on nodes per response, whatever the client asks for."""
MAX_VIEWPORT_EDGES: Final = 5000
"""Default server ceiling on edges per response (configurable down or up via ``ViewportLimits``)."""
DEFAULT_NODE_BUDGET: Final = 500
DEFAULT_EDGE_BUDGET: Final = 1000

Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class ViewportLimits:
    """Server-side ceilings. ``max_nodes`` can never exceed :data:`MAX_VIEWPORT_NODES`."""

    max_nodes: int = MAX_VIEWPORT_NODES
    max_edges: int = MAX_VIEWPORT_EDGES
    delayed_after_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not 1 <= self.max_nodes <= MAX_VIEWPORT_NODES:
            raise ValueError(f"max_nodes must be within 1..{MAX_VIEWPORT_NODES}")
        if self.max_edges < 1:
            raise ValueError("max_edges must be positive")


def get_graph(request: Request) -> GraphQuery:
    graph = getattr(request.app.state, "catalog_graph", None)
    if not isinstance(graph, GraphQuery):
        raise DependencyTransientError(
            "catalog graph is not configured", reason="catalog_graph_unconfigured"
        )
    return graph


def get_repository(request: Request) -> CatalogRepository:
    repository = getattr(request.app.state, "catalog_repository", None)
    if not isinstance(repository, CatalogRepository):
        raise DependencyTransientError(
            "catalog repository is not configured", reason="catalog_repository_unconfigured"
        )
    return repository


def get_aggregate_reader(request: Request) -> AggregateReader:
    reader = getattr(request.app.state, "aggregate_reader", None)
    if not isinstance(reader, AggregateReader):
        raise DependencyTransientError(
            "aggregate reader is not configured", reason="aggregates_unconfigured"
        )
    return reader


def get_pseudonymizer(request: Request) -> PrincipalPseudonymizer:
    pseudonymizer = getattr(request.app.state, "map_pseudonymizer", None)
    if not isinstance(pseudonymizer, PrincipalPseudonymizer):
        raise DependencyTransientError(
            "pseudonymizer is not configured", reason="pseudonymizer_unconfigured"
        )
    return pseudonymizer


def get_limits(request: Request) -> ViewportLimits:
    limits = getattr(request.app.state, "map_viewport_limits", None)
    return limits if isinstance(limits, ViewportLimits) else ViewportLimits()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def get_clock() -> Clock:
    return _utc_now
