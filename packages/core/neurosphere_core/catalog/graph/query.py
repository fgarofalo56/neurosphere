"""Bounded ``GraphQuery`` over any ``CatalogRepository`` (PRP-10 item 2).

Cosmos NoSQL is not a native graph engine and there is no graph query language here. Every
read is one of four structured operations (get, search, neighbors, impact paths) executed as
a breadth-first walk over ``CatalogRepository.list_edges_by_node``.

Budgets (every walk is bounded; nothing is unlimited):

* depth: nodes at ``budget.max_depth`` are returned but never added beyond it; one probe
  query per frontier node decides whether anything lies further out (``max_depth``).
* fan-out: at most ``budget.limit`` edges are taken per expanded node. The edges are fetched
  with headroom (one full page), filtered by endpoint scope FIRST, and only then counted: a
  node is truncated when more than ``limit`` IN-SCOPE edges exist, so hidden out-of-scope edges
  never influence ``truncated``. If even the full page is not exhausted the node cannot be
  proven complete and is reported truncated too. The protocol has no fan-out reason, so it is
  reported as ``max_edges`` (a high-degree hub cannot cause an unbounded walk).
* nodes / edges: ``budget.max_nodes`` / ``budget.max_edges`` (server defaults when absent).
* time: an injected monotonic clock is checked before every repository call (``timeout_ms``),
  including the root read and the override batch; a walk that is out of time before it has a
  root returns an empty, truncated (``timeout_ms``) result.

Over budget the partial result is returned with ``truncated=True``; the walk stops at once
for edge and time budgets.

Scope: the repository already filters on the edge document's domain; this layer additionally
requires the OTHER endpoint to resolve through ``get_entity`` (scope-filtered). An edge to a
node outside the scope is dropped, so a path through such a node is cut there and never
bridged. Presented lineage runs every edge through ``rules.present_edge`` with its overrides;
rejected edges are hidden and not traversed. The ``raw`` view skips curation and requires an
Auditor scope, checked explicitly with ``repo.engine.auditor_domains`` (no probe call through
the unknown-edge fallback of ``list_observations``): a non-auditor request raises
``ForbiddenError``, never an empty result, and so does an edge in a non-audited domain.
An edge whose lock has expired is presented with its newest observation (``graph.latest``).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from neurosphere_contracts.query.v1.budget import Budget

from neurosphere_core.catalog import rules
from neurosphere_core.catalog.graph.latest import LatestObservationReader, wants_latest
from neurosphere_core.catalog.protocol import (
    CatalogEdge,
    CatalogEntity,
    CatalogRepository,
    Direction,
    EdgeFilter,
    GraphPath,
    GraphResult,
    GraphSearchRequest,
    GraphView,
    ImpactRequest,
    NeighborsRequest,
    PresentedEdge,
)
from neurosphere_core.catalog.repo.engine import auditor_domains
from neurosphere_core.errors.taxonomy import ForbiddenError
from neurosphere_core.paging import PageRequest
from neurosphere_core.paging.models import MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope
from neurosphere_core.search.protocol import (
    AuthorizedSearch,
    SearchFilters,
    SearchRequest,
)

TruncatedReason = Literal["max_nodes", "max_edges", "max_depth", "timeout_ms"]

DEFAULT_MAX_NODES = 1000
"""Server policy default when ``budget.max_nodes`` is absent (never unbounded)."""
DEFAULT_MAX_EDGES = 5000
"""Server policy default when ``budget.max_edges`` is absent (never unbounded)."""


class _OutOfTimeError(Exception):
    """The time budget ran out before the walk had a root."""


_RAW_DENIED = "raw observations require a security auditor scope"
_TIMED_OUT = GraphResult(nodes=[], edges=[], truncated=True, truncated_reason="timeout_ms")


@dataclass
class _Walk:
    """Mutable state of one bounded traversal."""

    root: CatalogEntity
    deadline: float
    max_nodes: int
    max_edges: int
    fan_out: int
    nodes: dict[str, CatalogEntity] = field(default_factory=dict)
    depth: dict[str, int] = field(default_factory=dict)
    parent: dict[str, tuple[str, str]] = field(default_factory=dict)
    edges: dict[str, PresentedEdge] = field(default_factory=dict)
    scope_cache: dict[str, CatalogEntity | None] = field(default_factory=dict)
    reason: TruncatedReason | None = None
    stopped: bool = False

    def truncate(self, reason: TruncatedReason, *, stop: bool = False) -> None:
        if self.reason is None:
            self.reason = reason
        self.stopped = self.stopped or stop


class RepositoryGraphQuery:
    """``GraphQuery`` implementation over a ``CatalogRepository`` and an ``AuthorizedSearch``."""

    def __init__(
        self,
        repository: CatalogRepository,
        search: AuthorizedSearch,
        *,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        default_max_nodes: int = DEFAULT_MAX_NODES,
        default_max_edges: int = DEFAULT_MAX_EDGES,
    ) -> None:
        self._repo = repository
        self._search = search
        self._clock = clock
        self._now = now
        self._default_nodes = default_max_nodes
        self._default_edges = default_max_edges

    # ------------------------------------------------------------------ get / search

    async def get(self, scope: IdentityScope, node_id: str) -> CatalogEntity | None:
        return await self._repo.get_entity(scope, node_id)

    async def search(self, scope: IdentityScope, request: GraphSearchRequest) -> GraphResult:
        """Delegate ranking to ``AuthorizedSearch``, then re-fetch every hit via the repository
        so an ID the repository does not return for this scope never surfaces."""
        deadline = self._clock() + request.budget.timeout_ms / 1000.0
        result = await self._search.search(
            scope.to_contract(),
            SearchRequest(
                term=request.term,
                filters=SearchFilters(
                    entities=request.filters.entity_types, domain_ids=request.filters.domain_ids
                ),
                budget=request.budget,
            ),
        )
        cap = request.budget.max_nodes or self._default_nodes
        wanted = request.filters.lifecycle_statuses
        nodes: list[CatalogEntity] = []
        reason: TruncatedReason | None = None
        if result.partial:
            reason = "timeout_ms" if result.partial_reason == "timeout_ms" else "max_nodes"
        for hit in result.hits:
            if self._clock() >= deadline:
                reason = reason or "timeout_ms"
                break
            if len(nodes) >= cap:
                reason = reason or "max_nodes"
                break
            entity = await self._repo.get_entity(scope, hit.id)
            if entity is None:
                continue
            if wanted is not None and entity.lifecycle_status.root not in wanted:
                continue
            nodes.append(entity)
        return GraphResult(
            nodes=nodes,
            edges=[],
            truncated=reason is not None,
            truncated_reason=reason,
            visited_nodes=len(result.hits),
        )

    # ------------------------------------------------------------------ traversals

    async def neighbors(self, scope: IdentityScope, request: NeighborsRequest) -> GraphResult:
        try:
            walk = await self._walk(
                scope,
                request.node_id,
                request.direction,
                request.filters,
                request.budget,
                request.view,
            )
        except _OutOfTimeError:
            return _TIMED_OUT.model_copy(deep=True)
        return self._result(walk, with_paths=False)

    async def impact_paths(self, scope: IdentityScope, request: ImpactRequest) -> GraphResult:
        direction: Direction = "out" if request.direction == "downstream" else "in"
        try:
            walk = await self._walk(
                scope, request.node_id, direction, request.filters, request.budget, request.view
            )
        except _OutOfTimeError:
            return _TIMED_OUT.model_copy(deep=True)
        return self._result(walk, with_paths=True)

    # ------------------------------------------------------------------ internals

    def _result(self, walk: _Walk | None, *, with_paths: bool) -> GraphResult:
        if walk is None:
            return GraphResult(nodes=[], edges=[])
        paths: list[GraphPath] = []
        if with_paths:
            for node_id in walk.nodes:
                if node_id == walk.root.id:
                    continue
                node_ids = [node_id]
                edge_ids: list[str] = []
                while node_ids[-1] != walk.root.id:
                    prev, via = walk.parent[node_ids[-1]]
                    node_ids.append(prev)
                    edge_ids.append(via)
                node_ids.reverse()
                edge_ids.reverse()
                paths.append(GraphPath(node_ids=node_ids, edge_ids=edge_ids))
        return GraphResult(
            nodes=list(walk.nodes.values()),
            edges=list(walk.edges.values()),
            paths=paths,
            truncated=walk.reason is not None,
            truncated_reason=walk.reason,
            visited_nodes=len(walk.nodes),
            visited_edges=len(walk.edges),
        )

    async def _walk(
        self,
        scope: IdentityScope,
        node_id: str,
        direction: Direction,
        flt: EdgeFilter,
        budget: Budget,
        view: GraphView,
    ) -> _Walk | None:
        deadline = self._clock() + budget.timeout_ms / 1000.0
        if view == "raw" and not auditor_domains(scope, self._now()):
            # Explicit, so a non-Auditor scope is refused even when the node has no edges.
            raise ForbiddenError(_RAW_DENIED)
        if self._clock() >= deadline:  # budget check before the root read
            raise _OutOfTimeError
        root = await self._repo.get_entity(scope, node_id)
        if root is None:
            return None
        walk = _Walk(
            root=root,
            deadline=deadline,
            max_nodes=budget.max_nodes or self._default_nodes,
            max_edges=budget.max_edges or self._default_edges,
            fan_out=min(budget.limit, MAX_PAGE_SIZE - 1),
        )
        walk.nodes[root.id] = root
        walk.depth[root.id] = 0
        walk.scope_cache[root.id] = root
        audited = frozenset(auditor_domains(scope, self._now())) if view == "raw" else frozenset()
        frontier = [root.id]
        for depth in range(1, budget.max_depth + 2):
            nxt: list[str] = []
            for current in frontier:
                if walk.stopped:
                    break
                await self._expand(
                    scope,
                    walk,
                    current,
                    depth,
                    direction,
                    flt,
                    view,
                    audited,
                    nxt,
                    budget.max_depth,
                )
            if walk.stopped:
                return walk
            frontier = nxt
            if not frontier:
                return walk
        return walk

    def _expired(self, walk: _Walk) -> bool:
        if self._clock() >= walk.deadline:
            walk.truncate("timeout_ms", stop=True)
            return True
        return False

    async def _in_scope(
        self, scope: IdentityScope, walk: _Walk, entity_id: str
    ) -> CatalogEntity | None:
        if entity_id in walk.scope_cache:
            return walk.scope_cache[entity_id]
        if self._expired(walk):
            return None
        entity = await self._repo.get_entity(scope, entity_id)
        walk.scope_cache[entity_id] = entity
        return entity

    async def _expand(
        self,
        scope: IdentityScope,
        walk: _Walk,
        current: str,
        depth: int,
        direction: Direction,
        flt: EdgeFilter,
        view: GraphView,
        audited: frozenset[str],
        nxt: list[str],
        max_depth: int,
    ) -> None:
        if self._expired(walk):
            return
        page = await self._repo.list_edges_by_node(
            scope, current, direction, flt, PageRequest(page_size=MAX_PAGE_SIZE)
        )
        edges: list[CatalogEdge] = sorted(page.items, key=lambda e: e.id)

        # Scope first, budget second: an out-of-scope endpoint is cut here and must not count
        # toward (or reveal itself through) the fan-out truncation.
        visible: list[tuple[CatalogEdge, str]] = []
        for edge in edges:
            other = edge.target_id if edge.source_id == current else edge.source_id
            if await self._in_scope(scope, walk, other) is None:
                if walk.stopped:
                    return
                continue  # out-of-scope endpoint: cut here, never bridged
            visible.append((edge, other))
        if len(visible) > walk.fan_out or (page.next_cursor is not None and edges):
            walk.truncate("max_edges")
            visible = visible[: walk.fan_out]

        candidates: list[tuple[CatalogEdge, str]] = []
        for edge, other in visible:
            if edge.id in walk.edges:
                continue
            if view == "raw" and edge.domain_id.root not in audited:
                raise ForbiddenError(_RAW_DENIED)
            candidates.append((edge, other))
        if not candidates:
            return

        if view == "presented" and self._expired(walk):
            return
        overrides = (
            await self._repo.list_overrides_for_edges(scope, [e.id for e, _ in candidates])
            if view == "presented"
            else {}
        )
        now = self._now()
        for edge, other in candidates:
            held = overrides.get(edge.id, ())
            latest = None
            if (
                view == "presented"
                and isinstance(self._repo, LatestObservationReader)
                and wants_latest(edge, held, now)
            ):
                if self._expired(walk):
                    return
                latest = await self._repo.latest_observation(scope, edge.id)
            presented = rules.present_edge(edge, held, now, latest)
            if presented.hidden:
                continue  # a curated reject hides the edge; it is not traversed either
            is_new = other not in walk.nodes
            if depth > max_depth:
                # Probe pass: the frontier is not expanded; only learn whether more exists.
                if is_new:
                    walk.truncate("max_depth", stop=True)
                    return
                continue
            if is_new and len(walk.nodes) >= walk.max_nodes:
                walk.truncate("max_nodes")
                continue
            if len(walk.edges) >= walk.max_edges:
                walk.truncate("max_edges", stop=True)
                return
            walk.edges[edge.id] = presented
            if is_new:
                entity = walk.scope_cache[other]
                assert entity is not None  # resolved above
                walk.nodes[other] = entity
                walk.depth[other] = depth
                walk.parent[other] = (current, edge.id)
                nxt.append(other)
