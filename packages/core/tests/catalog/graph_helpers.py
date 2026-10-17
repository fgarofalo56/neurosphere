"""Builders shared by the graph query tests (in-memory repository, stub search, fake clock)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

from neurosphere_contracts.catalog.v1.edge_override import EdgeOverride
from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.catalog import CatalogRepository, GraphQuery
from neurosphere_core.catalog.graph import RepositoryGraphQuery
from neurosphere_core.catalog.protocol import (
    CatalogEdge,
    EdgeFilter,
    EntityFilter,
    NeighborsRequest,
)
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.paging import Page, PageRequest
from neurosphere_core.scope import IdentityScope
from neurosphere_core.search.protocol import (
    SearchHit,
    SearchRequest,
    SearchResult,
)

from .repo_conformance import agent, dom, edge, edge_id, example, make_scope

NS = "acme"
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)

__all__ = [
    "NOW",
    "NS",
    "CountingRepo",
    "FakeClock",
    "StubSearch",
    "agent",
    "budget",
    "dom",
    "edge",
    "edge_id",
    "make_query",
    "make_scope",
    "neighbors_request",
    "nid",
    "override_for",
    "seed_chain",
]


def nid(name: str, ns: str = NS) -> str:
    return f"commercial:{ns}:foundry:agent:{name}"


def budget(**patch: Any) -> Budget:
    raw: dict[str, Any] = {"timeout_ms": 5000, "limit": 100, "max_depth": 5}
    raw.update(patch)
    return Budget.model_validate(raw)


def neighbors_request(node: str, **patch: Any) -> NeighborsRequest:
    raw: dict[str, Any] = {"node_id": nid(node), "budget": budget()}
    raw.update(patch)
    return NeighborsRequest.model_validate(raw)


class FakeClock:
    """Monotonic clock that advances ``step`` seconds on every read."""

    def __init__(self, step: float = 0.0) -> None:
        self.t = 0.0
        self.step = step

    def __call__(self) -> float:
        self.t += self.step
        return self.t


class StubSearch:
    """``AuthorizedSearch`` that returns fixed hit IDs and records what it was asked."""

    def __init__(self, hits: Sequence[str], *, partial: bool = False) -> None:
        self.hits = list(hits)
        self.partial = partial
        self.scopes: list[object] = []
        self.requests: list[SearchRequest] = []

    async def search(self, scope: ContractScope, request: SearchRequest) -> SearchResult:
        self.scopes.append(scope)
        self.requests.append(request)
        return SearchResult(
            hits=[
                SearchHit(id=h, score=float(len(self.hits) - i)) for i, h in enumerate(self.hits)
            ],
            matched=len(self.hits),
            partial=self.partial,
            partial_reason="limit" if self.partial else None,
        )


class CountingRepo:
    """Delegating repository wrapper that records ``list_edges_by_node`` page sizes."""

    def __init__(self, inner: CatalogRepository) -> None:
        self._inner = inner
        self.edge_pages: list[int] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def list_edges_by_node(
        self,
        scope: IdentityScope,
        node_id: str,
        direction: Any,
        flt: EdgeFilter,
        page: PageRequest,
    ) -> Page[CatalogEdge]:
        self.edge_pages.append(page.page_size)
        return await self._inner.list_edges_by_node(scope, node_id, direction, flt, page)

    async def list_entities(
        self, scope: IdentityScope, flt: EntityFilter, page: PageRequest
    ) -> Page[Any]:
        return await self._inner.list_entities(scope, flt, page)


def make_query(
    repo: CatalogRepository,
    *,
    search: StubSearch | None = None,
    clock: FakeClock | None = None,
    **kwargs: Any,
) -> GraphQuery:
    return RepositoryGraphQuery(
        repo, search or StubSearch([]), clock=clock or FakeClock(), now=lambda: NOW, **kwargs
    )


async def seed_chain(
    repo: InMemoryCatalogRepository, scope: IdentityScope, names: Sequence[str], domain: str = "a"
) -> list[CatalogEdge]:
    """Agents ``names`` linked ``n0 -> n1 -> ...`` by edges named ``<n0>-<n1>``."""
    for name in names:
        await repo.create_entity(scope, agent(NS, name, domain))
    edges: list[CatalogEdge] = []
    for src, dst in pairwise(names):
        edges.append(await repo.put_edge(scope, edge(NS, f"{src}-{dst}", src, dst, domain), None))
    return edges


def override_for(
    target: CatalogEdge,
    name: str,
    decision: str,
    *,
    decided_at: str = "2026-10-09T17:30:00Z",
    expiry: str | None = "2027-01-01T00:00:00Z",
    set_confidence: float | None = None,
) -> EdgeOverride:
    """A steward decision for ``target`` (``reject``, ``lock``, ...)."""
    raw = example("edge_override.lock.json")
    actor = raw["actor"]
    locks = decision in ("lock", "override")
    raw.update(
        id=f"commercial:{NS}:neurosphere:edge_override:{name}",
        edge_id=target.id,
        relation_type="invokes",
        expected_edge_version=int(target.version.root),
        expected_edge_etag=target.etag.root,
        customer_id=NS,
        domain_id=target.domain_id.root,
        decision=decision,
        decided_at=decided_at,
        set_confidence=set_confidence,
        add_evidence_ids=[],
        lock=(
            {"locked": True, "reason": "steward", "expiry": expiry, "actor": actor}
            if locks
            else None
        ),
    )
    return EdgeOverride.model_validate(raw)
