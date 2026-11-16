"""``latest_subject_points`` / ``newest_subject_points`` on the in-memory store."""

from __future__ import annotations

import pytest
from neurosphere_core.aggregates import (
    MAX_SUBJECT_KEYS_PER_READ,
    AggregateWindow,
    InMemoryAggregateStore,
    format_bucket,
)
from neurosphere_core.errors import InvalidSchemaError

from .support import CUST, DOMAIN, NOW, hour, point, window


async def _seed(store: InMemoryAggregateStore, *points) -> None:  # type: ignore[no-untyped-def]
    by_bucket: dict[tuple[str, str, str], list] = {}  # type: ignore[type-arg]
    for p in points:
        by_bucket.setdefault((p.customer_id, p.domain_id, p.bucket_start), []).append(p)
    for (cust, domain, start), docs in by_bucket.items():
        await store.replace_bucket(cust, domain, "hour", start, docs)


async def test_newest_bucket_wins_and_scope_is_respected() -> None:
    store = InMemoryAggregateStore()
    await _seed(
        store,
        point("agent:a", 1, p95=50),
        point("agent:a", 0, p95=70),
        point("agent:b", 1),
        point("agent:a", 0, domain="dom-other", p95=999),
        point("agent:a", 0, customer="cust-2", p95=998),
        point("model:p/m", 0),
    )
    found = await store.latest_subject_points(
        CUST, DOMAIN, "agent", ["agent:a", "agent:b", "agent:missing", "model:p/m"], window()
    )
    assert sorted(found.points) == ["agent:a", "agent:b"]  # kind filter, absent key omitted
    assert found.points["agent:a"].p95_ms == 70
    assert found.points["agent:b"].bucket_start == format_bucket(hour(1))
    assert found.truncated is False


async def test_window_excludes_older_points() -> None:
    store = InMemoryAggregateStore()
    await _seed(store, point("agent:a", 5))
    found = await store.latest_subject_points(CUST, DOMAIN, "agent", ["agent:a"], window(2))
    assert found.points == {}


async def test_keys_beyond_the_ceiling_are_dropped_and_flagged() -> None:
    store = InMemoryAggregateStore()
    keys = [f"agent:{n:05d}" for n in range(MAX_SUBJECT_KEYS_PER_READ + 5)]
    found = await store.latest_subject_points(CUST, DOMAIN, "agent", keys, window())
    assert found.truncated is True


async def test_hour_window_is_bounded() -> None:
    store = InMemoryAggregateStore()
    wide = AggregateWindow(start=NOW.replace(year=2026, month=10, day=1), end=NOW)
    with pytest.raises(InvalidSchemaError):
        await store.latest_subject_points(CUST, DOMAIN, "agent", ["agent:a"], wide)


async def test_newest_subject_points_ranks_by_newest_then_key() -> None:
    store = InMemoryAggregateStore()
    await _seed(
        store,
        point("agent:c", 1),
        point("agent:b", 0),
        point("agent:a", 0),
        point("model:p/m", 0),
    )
    found = await store.newest_subject_points(CUST, DOMAIN, window(), 3)
    assert sorted(found.points) == ["agent:a", "agent:b", "model:p/m"]
    assert found.truncated is True
    assert (await store.newest_subject_points(CUST, DOMAIN, window(), 10)).truncated is False
