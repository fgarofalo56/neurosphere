"""PRP-43 item 3: bounded endpoint reads, scope-filtered fan-out, neutral auditor module."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from neurosphere_core.catalog import auditor
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.catalog.repo import engine as repo_engine
from neurosphere_core.scope import IdentityScope

from .graph_helpers import (
    NS,
    agent,
    budget,
    dom,
    edge,
    make_query,
    make_scope,
    neighbors_request,
)

DELAY = 0.01


class SlowRepo:
    """Delegates to a real repo; ``get_entity`` sleeps and records calls and concurrency."""

    def __init__(self, inner: InMemoryCatalogRepository) -> None:
        self._inner = inner
        self.reads: list[str] = []
        self.live = 0
        self.peak = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def get_entity(self, scope: IdentityScope, entity_id: str) -> Any:
        self.reads.append(entity_id)
        self.live += 1
        self.peak = max(self.peak, self.live)
        try:
            await asyncio.sleep(DELAY)
            return await self._inner.get_entity(scope, entity_id)
        finally:
            self.live -= 1


async def _hub(spokes: int, *, foreign: int = 0) -> tuple[InMemoryCatalogRepository, IdentityScope]:
    inner = InMemoryCatalogRepository()
    wide = make_scope(NS, [dom(NS, "a"), dom(NS, "b")])
    await inner.create_entity(wide, agent(NS, "hub", "a"))
    for i in range(spokes):
        await inner.create_entity(wide, agent(NS, f"s{i:03d}", "a"))
        await inner.put_edge(wide, edge(NS, f"hub-s{i:03d}", "hub", f"s{i:03d}", "a"), None)
    for i in range(foreign):
        await inner.create_entity(wide, agent(NS, f"f{i:03d}", "b"))
        await inner.put_edge(wide, edge(NS, f"hub-f{i:03d}", "hub", f"f{i:03d}", "b"), None)
    return inner, make_scope(NS, [dom(NS, "a")])


async def test_endpoint_reads_are_bounded_and_distinct() -> None:
    inner, scope = await _hub(48)
    repo = SlowRepo(inner)
    query = make_query(repo)  # type: ignore[arg-type]
    request = neighbors_request("hub", direction="out", budget=budget(max_depth=1, limit=100))
    started = time.perf_counter()
    result = await query.neighbors(scope, request)
    elapsed = time.perf_counter() - started
    assert len(result.nodes) == 49
    assert len(repo.reads) == len(set(repo.reads))  # at most one get_entity per distinct id
    assert repo.peak <= 16
    assert repo.peak > 1
    assert elapsed < 48 * DELAY  # the sequential baseline


async def test_foreign_edges_do_not_trigger_max_edges() -> None:
    inner, scope = await _hub(5, foreign=600)  # > 500 edges, only 5 in scope
    query = make_query(inner)
    request = neighbors_request("hub", direction="out", budget=budget(max_depth=1, limit=10))
    result = await query.neighbors(scope, request)
    assert result.truncated is False
    assert len([e for e in result.edges]) == 5


async def test_more_than_fan_out_in_scope_edges_reports_max_edges() -> None:
    inner, scope = await _hub(15, foreign=600)
    query = make_query(inner)
    request = neighbors_request("hub", direction="out", budget=budget(max_depth=1, limit=10))
    result = await query.neighbors(scope, request)
    assert result.truncated is True
    assert result.truncated_reason == "max_edges"
    assert len(result.edges) == 10


def test_auditor_domains_lives_in_neutral_module() -> None:
    assert repo_engine.auditor_domains is auditor.auditor_domains
    source = open(
        __import__("neurosphere_core.catalog.graph.query", fromlist=["x"]).__file__,
        encoding="utf-8",
    ).read()
    assert "from neurosphere_core.catalog.repo.engine" not in source
