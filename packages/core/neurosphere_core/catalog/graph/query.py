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
Auditor scope, checked explicitly with ``catalog.auditor.auditor_domains`` (no probe call through
the unknown-edge fallback of ``list_observations``): a non-auditor request raises
``ForbiddenError``, never an empty result, and so does an edge in a non-audited domain.
An edge whose lock has expired is presented with its newest observation (``graph.latest``).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from neurosphere_contracts.query.v1.budget import Budget

from neurosphere_core.catalog import rules
from neurosphere_core.catalog.auditor import auditor_domains
from neurosphere_core.catalog.graph.bulk import BULK_EDGE_PAGES, BULK_SCAN_PAGES, NODE_READ_CHUNK
from neurosphere_core.catalog.graph.latest import LatestObservationReader, wants_latest
from neurosphere_core.catalog.protocol import (
    MAX_EDGES_PER_OVERRIDE_BATCH,
    CatalogEdge,
    CatalogEntity,
    CatalogRepository,
    Direction,
    EdgeFilter,
    EntityFilter,
    GraphPath,
    GraphResult,
    GraphSearchRequest,
    GraphView,
    ImpactRequest,
    NeighborsRequest,
    PresentedEdge,
)
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


def _domain_of(entity: CatalogEntity) -> str | None:
    """The domain an entity lives in (a Domain entity is its own domain)."""
    if entity.entity_type == "domain":
        return entity.id
    domain = getattr(entity, "domain_id", None)
    return None if domain is None else str(domain.root)


_ENDPOINT_READ_CONCURRENCY = 16
_FAN_OUT_PAGES = 20
"""Edge pages read per node while counting in-scope edges (bounded; the deadline also applies)."""
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

    async def edges_among(
        self,
        scope: IdentityScope,
        node_ids: Collection[str],
        budget: Budget,
        view: GraphView = "presented",
    ) -> GraphResult:
        """Edges with both endpoints in ``node_ids`` (``EdgesAmongQuery``), each node read once.

        Same presented-view rules as ``_expand`` (hidden edges dropped, locks, overrides,
        expired-lock latest observation) and the same scope rule: ids that do not resolve
        through ``get_entity`` are dropped, so no edge to or from them is returned.
        """
        deadline = self._clock() + budget.timeout_ms / 1000.0
        if view == "raw" and not auditor_domains(scope, self._now()):
            raise ForbiddenError(_RAW_DENIED)
        audited = frozenset(auditor_domains(scope, self._now())) if view == "raw" else frozenset()
        max_nodes = budget.max_nodes or self._default_nodes
        max_edges = budget.max_edges or self._default_edges
        reason: TruncatedReason | None = None

        wanted = sorted(set(node_ids))
        if len(wanted) > max_nodes:
            wanted = wanted[:max_nodes]
            reason = "max_nodes"

        nodes, reason, timed_out = await self._bulk_nodes(scope, wanted, deadline, reason)
        if timed_out:
            return self._bulk_result(nodes, {}, reason)
        candidates, reason, timed_out = await self._bulk_candidates(
            scope, nodes, view, audited, deadline, reason
        )
        if timed_out:
            return self._bulk_result(nodes, {}, reason)

        ordered = [candidates[k] for k in sorted(candidates)]
        presented: dict[str, PresentedEdge] = {}
        now = self._now()
        batch = MAX_EDGES_PER_OVERRIDE_BATCH
        for start in range(0, len(ordered), batch):
            if self._clock() >= deadline:
                return self._bulk_result(nodes, presented, reason or "timeout_ms")
            group = ordered[start : start + batch]
            overrides = (
                await self._repo.list_overrides_for_edges(scope, [e.id for e in group])
                if view == "presented"
                else {}
            )
            for edge in group:
                held = overrides.get(edge.id, ())
                latest = None
                if (
                    view == "presented"
                    and isinstance(self._repo, LatestObservationReader)
                    and wants_latest(edge, held, now)
                ):
                    if self._clock() >= deadline:
                        return self._bulk_result(nodes, presented, reason or "timeout_ms")
                    latest = await self._repo.latest_observation(scope, edge.id)
                item = rules.present_edge(edge, held, now, latest)
                if item.hidden:
                    continue
                if len(presented) >= max_edges:
                    return self._bulk_result(nodes, presented, "max_edges")
                presented[edge.id] = item
        return self._bulk_result(nodes, presented, reason)

    async def _bulk_nodes(
        self,
        scope: IdentityScope,
        wanted: list[str],
        deadline: float,
        reason: TruncatedReason | None,
    ) -> tuple[dict[str, CatalogEntity], TruncatedReason | None, bool]:
        """Resolve ``wanted`` through the scoped repository (never trusting the caller).

        Entities come back ordered by id in pages, so the listing stops once it has passed the
        largest wanted id; ids still unresolved after the page cap are read one by one (bounded
        by ``max_nodes``). Returns (nodes, reason, timed_out).
        """
        nodes: dict[str, CatalogEntity] = {}
        if not wanted:
            return nodes, reason, False
        want = set(wanted)
        last = wanted[-1]
        cursor: str | None = None
        exhausted = False
        for _ in range(BULK_SCAN_PAGES):
            if self._clock() >= deadline:
                return nodes, reason or "timeout_ms", True
            page = await self._repo.list_entities(
                scope, EntityFilter(), PageRequest(page_size=MAX_PAGE_SIZE, cursor=cursor)
            )
            for entity in page.items:
                if entity.id in want:
                    nodes[entity.id] = entity
            cursor = page.next_cursor
            if cursor is None or (page.items and page.items[-1].id >= last):
                exhausted = True
                break
        if exhausted:
            return nodes, reason, False
        missing = [i for i in wanted if i not in nodes]
        for start in range(0, len(missing), NODE_READ_CHUNK):
            if self._clock() >= deadline:
                return nodes, reason or "timeout_ms", True
            chunk = missing[start : start + NODE_READ_CHUNK]
            found = await asyncio.gather(*(self._repo.get_entity(scope, i) for i in chunk))
            for entity_id, entity in zip(chunk, found, strict=True):
                if entity is not None:
                    nodes[entity_id] = entity
        return nodes, reason, False

    async def _bulk_candidates(
        self,
        scope: IdentityScope,
        nodes: dict[str, CatalogEntity],
        view: GraphView,
        audited: frozenset[str],
        deadline: float,
        reason: TruncatedReason | None,
    ) -> tuple[dict[str, CatalogEdge], TruncatedReason | None, bool]:
        """Stored edges with both endpoints in ``nodes``.

        First choice: page the edges of the nodes' domains (a handful of ordered pages). When a
        domain has more edges than the page cap allows, that domain is read node by node
        instead, so the result is complete either way. Returns (candidates, reason, timed_out).
        """
        candidates: dict[str, CatalogEdge] = {}

        def keep(edge: CatalogEdge) -> None:
            if edge.source_id not in nodes or edge.target_id not in nodes:
                return  # other endpoint outside the id set or the scope
            if view == "raw" and edge.domain_id.root not in audited:
                raise ForbiddenError(_RAW_DENIED)
            candidates.setdefault(edge.id, edge)

        domains = sorted({d for d in map(_domain_of, nodes.values()) if d is not None})
        for domain_id in domains:
            cursor: str | None = None
            done = False
            for _ in range(BULK_EDGE_PAGES):
                if self._clock() >= deadline:
                    return candidates, reason or "timeout_ms", True
                page = await self._repo.list_edges_by_domain(
                    scope,
                    domain_id,
                    EdgeFilter(),
                    PageRequest(page_size=MAX_PAGE_SIZE, cursor=cursor),
                )
                for edge in page.items:
                    keep(edge)
                cursor = page.next_cursor
                if cursor is None:
                    done = True
                    break
            if done:
                continue
            members = sorted(i for i, e in nodes.items() if _domain_of(e) == domain_id)
            for start in range(0, len(members), NODE_READ_CHUNK):
                if self._clock() >= deadline:
                    return candidates, reason or "timeout_ms", True
                chunk = members[start : start + NODE_READ_CHUNK]
                pages = await asyncio.gather(
                    *(
                        self._repo.list_edges_by_node(
                            scope, i, "out", EdgeFilter(), PageRequest(page_size=MAX_PAGE_SIZE)
                        )
                        for i in chunk
                    )
                )
                for node_page in pages:
                    if node_page.next_cursor is not None and node_page.items:
                        reason = reason or "max_edges"  # not exhausted: cannot prove complete
                    for edge in node_page.items:
                        keep(edge)
        return candidates, reason, False

    @staticmethod
    def _bulk_result(
        nodes: dict[str, CatalogEntity],
        edges: dict[str, PresentedEdge],
        reason: TruncatedReason | None,
    ) -> GraphResult:
        return GraphResult(
            nodes=list(nodes.values()),
            edges=list(edges.values()),
            truncated=reason is not None,
            truncated_reason=reason,
            visited_nodes=len(nodes),
            visited_edges=len(edges),
        )

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

    async def _resolve_scope(
        self, scope: IdentityScope, walk: _Walk, entity_ids: list[str]
    ) -> None:
        """Fill ``walk.scope_cache`` for ``entity_ids``: distinct ids, bounded concurrency."""
        unseen = [i for i in dict.fromkeys(entity_ids) if i not in walk.scope_cache]
        if not unseen:
            return
        if self._expired(walk):
            return
        gate = asyncio.Semaphore(_ENDPOINT_READ_CONCURRENCY)

        async def read(entity_id: str) -> CatalogEntity | None:
            async with gate:
                return await self._repo.get_entity(scope, entity_id)

        found = await asyncio.gather(*(read(i) for i in unseen))
        for entity_id, entity in zip(unseen, found, strict=True):
            walk.scope_cache[entity_id] = entity

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
        # Scope first, budget second: an out-of-scope endpoint is cut here and must not count
        # toward (or reveal itself through) the fan-out truncation. So page on until more than
        # ``fan_out`` IN-SCOPE edges are seen or the node's edges are exhausted (PRP-43 item 3).
        visible: list[tuple[CatalogEdge, str]] = []
        cursor: str | None = None
        more = False
        for _ in range(_FAN_OUT_PAGES):
            page = await self._repo.list_edges_by_node(
                scope, current, direction, flt, PageRequest(page_size=MAX_PAGE_SIZE, cursor=cursor)
            )
            edges: list[CatalogEdge] = sorted(page.items, key=lambda e: e.id)
            others = [e.target_id if e.source_id == current else e.source_id for e in edges]
            await self._resolve_scope(scope, walk, others)
            if walk.stopped:
                return
            visible.extend(
                (edge, other)
                for edge, other in zip(edges, others, strict=True)
                if walk.scope_cache.get(other) is not None
            )
            cursor = page.next_cursor
            more = cursor is not None and bool(edges)
            if not more or len(visible) > walk.fan_out:
                break
        if len(visible) > walk.fan_out or more:
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
