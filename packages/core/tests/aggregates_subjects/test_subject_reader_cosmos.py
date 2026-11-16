"""``CosmosAggregateStore`` subject reads over the strict fake container."""

from __future__ import annotations

from typing import Any

from neurosphere_core.aggregates import SubjectMetricsReader
from neurosphere_core.aggregates.cosmos import CosmosAggregateStore
from neurosphere_core.aggregates.subject import KEYS_PER_QUERY

from .cosmos_fake import new_container
from .support import CUST, DOMAIN, point, window


async def _store_with(*points: Any) -> tuple[CosmosAggregateStore, Any]:
    container = new_container()
    store = CosmosAggregateStore(container)
    for p in points:
        await container.upsert_item(p.model_dump(mode="json"))
    return store, container


async def test_implements_the_reader_protocol() -> None:
    store, _ = await _store_with()
    assert isinstance(store, SubjectMetricsReader)


async def test_latest_point_per_key_scoped_to_customer_and_domain() -> None:
    store, container = await _store_with(
        point("agent:a", 1, p95=10),
        point("agent:a", 0, p95=20),
        point("agent:a", 0, domain="dom-other", p95=999),
        point("agent:a", 0, customer="cust-2", p95=998),
        point("model:p/m", 0),
    )
    found = await store.latest_subject_points(
        CUST, DOMAIN, "agent", ["agent:a", "agent:none"], window()
    )
    assert list(found.points) == ["agent:a"]
    assert found.points["agent:a"].p95_ms == 20
    assert all(q.partition_key == (CUST,) for q in container.queries)


async def test_keys_are_chunked_at_100_per_query() -> None:
    keys = [f"agent:{n:04d}" for n in range(250)]
    store, container = await _store_with(*(point(k) for k in keys))
    found = await store.latest_subject_points(CUST, DOMAIN, "agent", keys, window())
    assert len(found.points) == 250
    assert len(container.queries) == 3
    assert KEYS_PER_QUERY == 100
    assert max(len(q.params) for q in container.queries) <= 105


async def test_newest_subject_points_is_bounded() -> None:
    store, _ = await _store_with(point("agent:a", 1), point("agent:b", 0), point("model:p/m", 0))
    found = await store.newest_subject_points(CUST, DOMAIN, window(), 2)
    assert sorted(found.points) == ["agent:b", "model:p/m"]
    assert found.truncated is True
