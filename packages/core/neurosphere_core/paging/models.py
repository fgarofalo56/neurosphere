"""Pagination and budget models. Every list/traversal surface is bounded; nothing is unlimited."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

MAX_PAGE_SIZE = 500
DEFAULT_PAGE_SIZE = 50

Cursor = Annotated[str, Field(min_length=1, max_length=2048, pattern=r"^[A-Za-z0-9_\-=.~]+$")]


class PageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    page_size: Annotated[int, Field(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE
    cursor: Cursor | None = None


class Page[T](BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: Annotated[tuple[T, ...], Field(max_length=MAX_PAGE_SIZE)]
    next_cursor: Cursor | None = None


class TraversalBudget(BaseModel):
    """Node, edge and wall-clock ceilings for one graph traversal or analytics request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_nodes: Annotated[int, Field(ge=1, le=100_000)] = 5_000
    max_edges: Annotated[int, Field(ge=1, le=500_000)] = 20_000
    max_duration_ms: Annotated[int, Field(ge=1, le=60_000)] = 5_000

    def clamp(self, ceiling: TraversalBudget) -> TraversalBudget:
        """Return the per-field minimum, so a caller can lower but never raise a server ceiling."""
        return TraversalBudget(
            max_nodes=min(self.max_nodes, ceiling.max_nodes),
            max_edges=min(self.max_edges, ceiling.max_edges),
            max_duration_ms=min(self.max_duration_ms, ceiling.max_duration_ms),
        )
