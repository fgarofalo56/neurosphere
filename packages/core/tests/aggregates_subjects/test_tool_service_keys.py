"""Tool and service subject kinds (PRP-100 item 2): keys, reader scoping, realtime guard."""

from __future__ import annotations

import pytest
from neurosphere_core.aggregates import (
    AggregateStatus,
    AggregateWindow,
    InMemoryAggregateStore,
    SubjectPoint,
    format_bucket,
    health_for_error_rate,
    subject_series_key,
)

from .support import CUST, DOMAIN, NOW, point, window

TOOL = "tool:commercial:c:s:tool:search"
SERVICE = "service:commercial:c:s:service:db"


def test_keys_for_each_kind() -> None:
    assert subject_series_key("tool", "commercial:c:s:tool:search") == TOOL
    assert subject_series_key("service", "commercial:c:s:service:db") == SERVICE
    assert subject_series_key("agent", "commercial:c:s:agent:a") == "agent:commercial:c:s:agent:a"
    assert subject_series_key("model", " OpenAI ", "GPT-4o") == "model:openai/gpt-4o"
    with pytest.raises(ValueError):
        subject_series_key("model", "openai")


async def _seed(store: InMemoryAggregateStore, *points: SubjectPoint) -> None:
    by_bucket: dict[tuple[str, str, str], list[SubjectPoint]] = {}
    for p in points:
        by_bucket.setdefault((p.customer_id, p.domain_id, p.bucket_start), []).append(p)
    for (cust, domain, start), docs in by_bucket.items():
        await store.replace_bucket(cust, domain, "hour", start, docs)


async def test_reader_returns_tool_and_service_scoped_to_customer_and_domain() -> None:
    store = InMemoryAggregateStore()
    await _seed(
        store,
        point(TOOL),
        point(SERVICE),
        point(TOOL, domain="dom-other", p95=999),
        point(TOOL, customer="cust-2", p95=998),
        point("agent:a"),
        point("model:p/m"),
    )
    tools = await store.latest_subject_points(CUST, DOMAIN, "tool", [TOOL, SERVICE], window())
    assert list(tools.points) == [TOOL]
    assert tools.points[TOOL].subject_kind == "tool" and tools.points[TOOL].p95_ms == 120
    services = await store.latest_subject_points(CUST, DOMAIN, "service", [TOOL, SERVICE], window())
    assert list(services.points) == [SERVICE]
    # a cross-customer read never sees the other customer's point
    other = await store.latest_subject_points("cust-2", DOMAIN, "service", [SERVICE], window())
    assert other.points == {}


async def test_newest_subject_points_never_returns_tool_or_service() -> None:
    store = InMemoryAggregateStore()
    await _seed(store, point(TOOL), point(SERVICE), point("agent:a"), point("model:p/m"))
    found = await store.newest_subject_points(CUST, DOMAIN, window(), 10)
    assert sorted(found.points) == ["agent:a", "model:p/m"]
    assert found.truncated is False


@pytest.mark.parametrize(
    ("rate", "health"),
    [(0.04, "ok"), (0.05, "degraded"), (0.25, "failing"), (None, "unknown")],
)
async def test_health_for_tool_points_via_the_reader(rate: float | None, health: str) -> None:
    store = InMemoryAggregateStore()
    await _seed(store, point(TOOL, error_rate=rate))
    found = await store.latest_subject_points(CUST, DOMAIN, "tool", [TOOL], window())
    assert health_for_error_rate(found.points[TOOL].error_rate) == health


async def test_realtime_delta_has_no_node_for_tool_or_service() -> None:
    from neurosphere_api.realtime import RealtimeSettings
    from neurosphere_api.realtime.source import AggregateDeltaSource

    store = InMemoryAggregateStore()
    await _seed(store, point(TOOL), point(SERVICE), point("agent:commercial:c:s:agent:a"))
    await store.put_status(AggregateStatus(customer_id=CUST, watermark=format_bucket(NOW)))
    source = AggregateDeltaSource(store, RealtimeSettings(), clock=lambda: 0.0)  # type: ignore[arg-type]
    payload = await source.poll(CUST, DOMAIN, NOW)
    assert [n.kind for n in payload.nodes] == ["cluster", "agent"]
    # the source's own filter also holds when handed a tool point directly
    assert source._subject_node(point(TOOL)) is None


def test_window_type_is_used() -> None:
    assert isinstance(window(), AggregateWindow)
