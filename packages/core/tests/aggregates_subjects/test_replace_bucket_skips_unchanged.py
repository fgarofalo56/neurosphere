"""``replace_bucket`` writes only changed documents (in-memory counter, Cosmos upsert log)."""

from __future__ import annotations

from typing import Any

from neurosphere_core.aggregates import InMemoryAggregateStore
from neurosphere_core.aggregates.cosmos import CosmosAggregateStore

from .cosmos_fake import new_container
from .support import CUST, DOMAIN, hour, point


def _start() -> str:
    return point("agent:a", 0).bucket_start


async def test_in_memory_skips_unchanged_documents() -> None:
    store = InMemoryAggregateStore()
    docs = [point("agent:a"), point("agent:b"), point("model:p/m")]
    await store.replace_bucket(CUST, DOMAIN, "hour", _start(), docs)
    assert store.document_writes == 3
    await store.replace_bucket(CUST, DOMAIN, "hour", _start(), docs)
    assert store.document_writes == 3  # same input: nothing written
    changed = [point("agent:a", events=9), *docs[1:]]
    await store.replace_bucket(CUST, DOMAIN, "hour", _start(), changed)
    assert store.document_writes == 4  # exactly the changed document
    await store.replace_bucket(CUST, DOMAIN, "hour", _start(), changed[:2])
    assert sorted(d.series_key for d in store.documents(CUST).values()) == ["agent:a", "agent:b"]


async def test_cosmos_skips_unchanged_documents() -> None:
    container: Any = new_container()
    writes: list[str] = []
    original = container.upsert_item

    async def counting(body: Any) -> Any:
        writes.append(body["id"])
        return await original(body)

    container.upsert_item = counting
    store = CosmosAggregateStore(container)
    docs = [point("agent:a"), point("agent:b")]
    await store.replace_bucket(CUST, DOMAIN, "hour", _start(), docs)
    assert len(writes) == 2
    await store.replace_bucket(CUST, DOMAIN, "hour", _start(), docs)
    assert len(writes) == 2
    await store.replace_bucket(
        CUST, DOMAIN, "hour", _start(), [point("agent:a", events=7), docs[1]]
    )
    assert len(writes) == 3
    assert hour(0)  # bucket helper stays in use
