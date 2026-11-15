"""Two concurrent puts of one recommendation id into different partitions leave exactly one copy
(#133 bullet 2): the copy in the smallest ``[customer, domain]`` partition."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from neurosphere_core.recommendations import InMemoryRecommendationStore, RecommendationStore
from neurosphere_core.recommendations.cosmos_store import CosmosRecommendationStore

from .conformance import FINANCE, OPERATIONS, ids, make_scope, rec
from .cosmos_fake import new_container
from .fake_container import FakeContainer


class _LockstepContainer:
    """Wraps the fake so the first ``parties`` writers all upsert before any of them queries:
    the interleaving in which each writer sees the other's copy."""

    def __init__(self, inner: FakeContainer, parties: int) -> None:
        self._inner = inner
        self._parties = parties
        self._upserted = 0
        self._gate = asyncio.Event()

    async def upsert_item(self, body: Any) -> Any:
        result = await self._inner.upsert_item(body)
        self._upserted += 1
        if self._upserted >= self._parties:
            self._gate.set()
        return result

    async def query_items(self, *args: Any, **kwargs: Any) -> Any:
        await self._gate.wait()
        async for row in self._inner.query_items(*args, **kwargs):
            yield row

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _copies(container: FakeContainer) -> list[str]:
    return sorted(doc["domain_id"] for doc in container.items.values())


@pytest.mark.parametrize("order", ["finance_first", "operations_first"])
async def test_concurrent_puts_in_two_partitions_leave_one_copy(order: str) -> None:
    inner = new_container()
    lockstep = _LockstepContainer(inner, parties=2)
    # Two store instances (two worker processes) over one container.
    one = CosmosRecommendationStore(lockstep)  # type: ignore[arg-type]
    two = CosmosRecommendationStore(lockstep)  # type: ignore[arg-type]
    puts = [one.put(rec(1, domain=FINANCE)), two.put(rec(1, domain=OPERATIONS))]
    if order == "operations_first":
        puts.reverse()
    await asyncio.gather(*puts)
    assert _copies(inner) == [FINANCE]


async def test_sequential_puts_in_either_order_keep_the_smallest_partition() -> None:
    for first, second in ((FINANCE, OPERATIONS), (OPERATIONS, FINANCE)):
        inner = new_container()
        store = CosmosRecommendationStore(inner)  # type: ignore[arg-type]
        await store.put(rec(1, domain=first))
        await store.put(rec(1, domain=second))
        assert _copies(inner) == [FINANCE]


async def test_a_larger_partition_copy_that_pre_exists_is_cleaned_by_the_next_put() -> None:
    inner = new_container()
    store = CosmosRecommendationStore(inner)  # type: ignore[arg-type]
    await store.put(rec(1, domain=OPERATIONS))
    # A copy in a smaller partition arrives (for example from an older writer): the next put
    # from either side converges on it.
    await inner.upsert_item({**rec(1, domain=FINANCE).model_dump(mode="json"), **_row_fields(1)})
    await store.put(rec(1, domain=OPERATIONS))
    assert _copies(inner) == [FINANCE]


def _row_fields(n: int) -> dict[str, Any]:
    rid = rec(n).recommendation_id.root
    return {"id": rid, "doc_type": "recommendation", "sort_key": rid}


@pytest.mark.parametrize("make", [InMemoryRecommendationStore])
async def test_in_memory_store_follows_the_same_rule(
    make: type[InMemoryRecommendationStore],
) -> None:
    store: RecommendationStore = make()
    both = make_scope([FINANCE, OPERATIONS])
    await asyncio.gather(store.put(rec(1, domain=OPERATIONS)), store.put(rec(1, domain=FINANCE)))
    assert ids(await store.list(both, FINANCE)) == ["rec-0001"]
    assert ids(await store.list(both, OPERATIONS)) == []
