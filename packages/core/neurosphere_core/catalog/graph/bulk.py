"""Bulk "edges among these ids" read (PRP-18 round 2 item 1).

``EdgesAmongQuery`` is deliberately separate from ``catalog.protocol.GraphQuery`` (PRP-43 owns
that protocol): a graph that lacks the method is still a valid ``GraphQuery`` and callers fall
back to a per-node walk.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Protocol, runtime_checkable

from neurosphere_contracts.query.v1.budget import Budget

from neurosphere_core.catalog.protocol import GraphResult, GraphView
from neurosphere_core.scope import IdentityScope

NODE_READ_CHUNK = 32
"""Concurrent repository reads per round (bounded fan-out; the clock is checked per round)."""
BULK_EDGE_PAGES = 40
"""Edge pages (of 500) read per domain before that domain is read node by node."""
BULK_SCAN_PAGES = 20
"""Entity pages (of 500) read to resolve an id set before falling back to per-id reads."""


@runtime_checkable
class EdgesAmongQuery(Protocol):
    """Edges whose BOTH endpoints are in a given id set, in one bounded call."""

    async def edges_among(
        self,
        scope: IdentityScope,
        node_ids: Collection[str],
        budget: Budget,
        view: GraphView = "presented",
    ) -> GraphResult:
        """The presented (or raw, Auditor-only) edges between ``node_ids``.

        ``nodes`` holds the ids that resolve in ``scope``; ``edges`` only edges with both
        endpoints among them, so an out-of-scope endpoint never contributes an edge.
        ``budget.max_nodes`` caps the ids read, ``budget.max_edges`` the edges returned and
        ``budget.timeout_ms`` the wall time; any hit sets ``truncated`` and the reason.
        """
        ...
