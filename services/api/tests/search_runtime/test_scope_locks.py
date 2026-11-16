"""Per-scope refresh locks: a slow scope never delays another; same-scope callers single-flight."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

from neurosphere_api.runtime.builders import search as search_module
from neurosphere_api.runtime.builders.search import IndexedGraphQuery


class GatedIndexer:
    """Refresh blocks on a per-scope gate until released; counts calls per scope."""

    def __init__(self) -> None:
        self.gates: dict[str, asyncio.Event] = {}
        self.calls: dict[str, int] = {}

    async def refresh(self, scope: Any) -> int:
        name = scope.scope_hash
        self.calls[name] = self.calls.get(name, 0) + 1
        gate = self.gates.get(name)
        if gate is not None:
            await gate.wait()
        return 0


def _scope(name: str) -> Any:
    return SimpleNamespace(scope_hash=name, allowed_domains=[f"d-{name}"])


def _graph(indexer: GatedIndexer) -> IndexedGraphQuery:
    return IndexedGraphQuery(
        cast(Any, None), cast(Any, None), cast(Any, indexer), refresh_seconds=3600
    )


async def test_slow_scope_does_not_delay_another_scope() -> None:
    indexer = GatedIndexer()
    indexer.gates["a"] = asyncio.Event()
    graph = _graph(indexer)
    slow = asyncio.create_task(graph._sync(_scope("a")))  # pyright: ignore[reportPrivateUsage]
    await asyncio.sleep(0)
    await asyncio.wait_for(graph._sync(_scope("b")), 1)  # pyright: ignore[reportPrivateUsage]
    assert not slow.done()
    indexer.gates["a"].set()
    await asyncio.wait_for(slow, 1)


async def test_concurrent_callers_for_one_scope_share_one_refresh() -> None:
    indexer = GatedIndexer()
    indexer.gates["a"] = asyncio.Event()
    graph = _graph(indexer)
    tasks = [
        asyncio.create_task(graph._sync(_scope("a")))  # pyright: ignore[reportPrivateUsage]
        for _ in range(5)
    ]
    await asyncio.sleep(0.01)
    indexer.gates["a"].set()
    await asyncio.wait_for(asyncio.gather(*tasks), 1)
    assert indexer.calls == {"a": 1}


async def test_lock_table_is_bounded(monkeypatch: Any) -> None:
    monkeypatch.setattr(search_module, "_SCOPE_CACHE_LIMIT", 8)
    indexer = GatedIndexer()
    graph = _graph(indexer)
    for i in range(50):
        await graph._sync(_scope(f"s{i}"))  # pyright: ignore[reportPrivateUsage]
    assert len(graph._locks) <= 8  # pyright: ignore[reportPrivateUsage]
