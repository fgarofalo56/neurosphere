"""Realtime delta source: agent and model nodes from the subject series (PRP-49 item 4)."""

from datetime import UTC, datetime, timedelta

from neurosphere_api.realtime import RealtimeSettings
from neurosphere_api.realtime.source import MAX_DELTA_SUBJECT_NODES, AggregateDeltaSource
from neurosphere_core.aggregates import (
    HEALTH_DEGRADED_ERROR_RATE,
    HEALTH_FAILING_ERROR_RATE,
    AggregateStatus,
    InMemoryAggregateStore,
    SubjectPoint,
    aggregate_doc_id,
    bucket_start,
    format_bucket,
)

CUST = "cust-1"
DOM = "dom-a"
NOW = datetime(2027, 1, 15, 8, 30, tzinfo=UTC)


def _point(
    key: str,
    *,
    hours_ago: int = 0,
    events: int = 3,
    p95: int | None = 200,
    error_rate: float | None = 0.0,
    tokens: tuple[int | None, int | None] = (10, 5),
) -> SubjectPoint:
    start = format_bucket(bucket_start(NOW, "hour") - timedelta(hours=hours_ago))
    return SubjectPoint(
        id=aggregate_doc_id(CUST, DOM, "subject", "hour", start, key),
        customer_id=CUST,
        domain_id=DOM,
        grain="hour",
        bucket_start=start,
        series_key=key,
        watermark=start,
        complete=True,
        subject_kind="agent" if key.startswith("agent:") else "model",
        subject_key=key,
        event_count=events,
        missing_duration_count=0,
        unknown_outcome_count=0,
        error_count=None if error_rate is None else 0,
        error_rate=error_rate,
        p95_ms=p95,
        input_tokens=tokens[0],
        output_tokens=tokens[1],
        tokens_known_count=events,
    )


async def _seed(store: InMemoryAggregateStore, *points: SubjectPoint) -> None:
    buckets: dict[str, list[SubjectPoint]] = {}
    for p in points:
        buckets.setdefault(p.bucket_start, []).append(p)
    for start, docs in buckets.items():
        await store.replace_bucket(CUST, DOM, "hour", start, docs)
    await store.put_status(
        AggregateStatus(customer_id=CUST, watermark=format_bucket(NOW - timedelta(seconds=1)))
    )


def _source(store: object, clock: list[float] | None = None) -> AggregateDeltaSource:
    ticks = clock if clock is not None else [0.0]
    return AggregateDeltaSource(store, RealtimeSettings(), clock=lambda: ticks[0])  # type: ignore[arg-type]


async def test_delta_carries_the_domain_node_plus_subject_nodes() -> None:
    store = InMemoryAggregateStore()
    await _seed(
        store,
        _point("agent:commercial:c:s:agent:alpha", events=7, p95=250, error_rate=0.1),
        _point("model:azure_openai/gpt-4o", events=9, error_rate=0.3),
        _point(
            "agent:commercial:c:s:agent:unknown", p95=None, error_rate=None, tokens=(None, None)
        ),
    )
    payload = await _source(store).poll(CUST, DOM, NOW)
    kinds = {n.id: n for n in payload.nodes}
    assert payload.nodes[0].kind == "cluster" and payload.nodes[0].id == DOM
    alpha = kinds["commercial:c:s:agent:alpha"]
    assert (alpha.kind, alpha.label) == ("agent", "alpha")
    assert (alpha.metrics.frequency, alpha.metrics.latency_p95_ms) == (7, 250)
    assert (alpha.metrics.tokens, alpha.metrics.health) == (15, "degraded")
    model = kinds["azure_openai/gpt-4o"]
    assert (model.kind, model.label, model.metrics.health) == ("model", "gpt-4o", "failing")
    unknown = kinds["commercial:c:s:agent:unknown"].metrics
    assert (unknown.latency_p95_ms, unknown.tokens, unknown.health) == (None, None, "unknown")


async def test_subject_nodes_are_bounded_to_the_newest_points() -> None:
    store = InMemoryAggregateStore()
    fresh = [_point(f"agent:a{n:03d}") for n in range(MAX_DELTA_SUBJECT_NODES)]
    stale = [_point(f"agent:old{n:03d}", hours_ago=1) for n in range(10)]
    await _seed(store, *fresh, *stale)
    payload = await _source(store).poll(CUST, DOM, NOW)
    ids = [n.id for n in payload.nodes[1:]]
    assert len(ids) == MAX_DELTA_SUBJECT_NODES
    assert not any(i.startswith("old") for i in ids)


async def test_reader_without_the_capability_gives_the_unchanged_one_node_delta() -> None:
    class Plain:
        def __init__(self, inner: InMemoryAggregateStore) -> None:
            self.query = inner.query
            self.status = inner.status

    store = InMemoryAggregateStore()
    await _seed(store, _point("agent:x"))
    payload = await _source(Plain(store)).poll(CUST, DOM, NOW)
    assert [n.kind for n in payload.nodes] == ["cluster"]


async def test_cache_ttl_and_digest_behaviour_are_unchanged() -> None:
    store = InMemoryAggregateStore()
    await _seed(store, _point("agent:x"))
    clock = [0.0]
    source = _source(store, clock)
    first = await source.poll(CUST, DOM, NOW)
    await _seed(store, _point("agent:x"), _point("agent:y"))
    assert await source.poll(CUST, DOM, NOW) is first  # inside the TTL: same object
    clock[0] = 10.0
    second = await source.poll(CUST, DOM, NOW)
    assert second.digest() != first.digest()
    again = await source.poll(CUST, DOM, NOW)  # recomputed later with no change
    clock[0] = 20.0
    assert (await source.poll(CUST, DOM, NOW)).digest() == again.digest()


def test_health_thresholds_equal_the_realtime_settings_defaults() -> None:
    settings = RealtimeSettings()
    assert settings.health_degraded_error_rate == HEALTH_DEGRADED_ERROR_RATE
    assert settings.health_failing_error_rate == HEALTH_FAILING_ERROR_RATE
