"""Per-node metrics from the subject aggregate series (PRP-49 item 3)."""

import asyncio
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from map_api_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    CUSTOMER,
    FINANCE,
    NOW,
    Api,
    agent_doc,
    agent_id,
    make_api,
    model_doc,
    person_doc,
)
from neurosphere_core.aggregates import (
    AggregateWindow,
    InMemoryAggregateStore,
    SubjectKind,
    SubjectLookup,
    SubjectPoint,
    aggregate_doc_id,
    bucket_start,
    format_bucket,
)


def _point(
    key: str,
    *,
    hours_ago: int = 0,
    events: int = 4,
    p95: int | None = 250,
    error_rate: float | None = 0.0,
    input_tokens: int | None = 100,
    output_tokens: int | None = 20,
    domain: str = FINANCE,
    customer: str | None = None,
) -> SubjectPoint:
    cust = customer or CUSTOMER
    start = format_bucket(bucket_start(NOW, "hour") - timedelta(hours=hours_ago))
    return SubjectPoint(
        id=aggregate_doc_id(cust, domain, "subject", "hour", start, key),
        customer_id=cust,
        domain_id=domain,
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
        p50_ms=p95,
        p95_ms=p95,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tokens_known_count=events,
    )


def _put(api: Api, *points: SubjectPoint) -> None:
    async def run() -> None:
        buckets: dict[tuple[str, str, str], list[SubjectPoint]] = {}
        for p in points:  # replace_bucket replaces the whole bucket: group first
            buckets.setdefault((p.customer_id, p.domain_id, p.bucket_start), []).append(p)
        for (cust, domain, start), docs in buckets.items():
            await api.store.replace_bucket(cust, domain, "hour", start, docs)

    asyncio.run(run())


def _by_label(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {n["label"]: n for n in body["nodes"]}


class SpyStore(InMemoryAggregateStore):
    """Counts subject reads; can be told to fail or hang."""

    def __init__(self, inner: InMemoryAggregateStore) -> None:
        super().__init__()
        self._docs = inner._docs
        self._status = inner._status
        self.calls: list[tuple[str, str, SubjectKind, int]] = []
        self.fail = False

    async def latest_subject_points(
        self,
        customer_id: str,
        domain_id: str,
        kind: SubjectKind,
        keys: Sequence[str],
        window: AggregateWindow,
    ) -> SubjectLookup:
        self.calls.append((customer_id, domain_id, kind, len(keys)))
        if self.fail:
            raise RuntimeError("subject read down")
        return await super().latest_subject_points(customer_id, domain_id, kind, keys, window)


def _spy(api: Api) -> SpyStore:
    spy = SpyStore(api.store)
    api.h.app.state.aggregate_reader = spy
    return spy


def test_agent_and_model_nodes_carry_metrics_from_the_latest_point() -> None:
    api = make_api()
    api.seed(agent_doc("alpha"), model_doc("dep-1"))
    _put(
        api,
        _point(f"agent:{agent_id('alpha')}", hours_ago=1, events=1, p95=900),
        _point(f"agent:{agent_id('alpha')}", events=7, p95=250, error_rate=0.1),
        _point("model:azure_openai/gpt-4o", events=9, p95=111, error_rate=0.3),
    )
    body = api.get(ALICE, FINANCE).json()
    agent = _by_label(body)["Agent alpha"]["metrics"]
    assert agent["frequency"] == 7
    assert agent["latency_p95_ms"] == 250
    assert agent["tokens"] == 120
    assert agent["health"] == "degraded"
    model = _by_label(body)["dep-1"]["metrics"]
    assert (model["frequency"], model["latency_p95_ms"], model["health"]) == (9, 111, "failing")
    assert model["context_size"] is not None  # the catalog fact is kept


def test_no_point_or_unknown_values_stay_null_and_unknown_never_zero() -> None:
    api = make_api()
    api.seed(agent_doc("quiet"), agent_doc("blank"))
    _put(
        api,
        _point(
            f"agent:{agent_id('blank')}",
            p95=None,
            error_rate=None,
            input_tokens=None,
            output_tokens=None,
        ),
        # Older than the two-bucket window: not observed.
        _point(f"agent:{agent_id('quiet')}", hours_ago=5),
    )
    nodes = _by_label(api.get(ALICE, FINANCE).json())
    quiet = nodes["Agent quiet"]["metrics"]
    assert quiet == {
        "tokens": None,
        "context_size": None,
        "frequency": None,
        "latency_p95_ms": None,
        "health": "unknown",
    }
    blank = nodes["Agent blank"]["metrics"]
    assert (blank["latency_p95_ms"], blank["tokens"], blank["health"]) == (None, None, "unknown")
    assert blank["frequency"] == 4  # counted spans, a known number


def test_model_match_is_case_insensitive_and_model_level() -> None:
    api = make_api()
    api.seed(model_doc("dep-1"), model_doc("dep-2"))
    _put(api, _point("model:azure_openai/gpt-4o", events=5))
    nodes = _by_label(api.get(ALICE, FINANCE).json())
    assert nodes["dep-1"]["metrics"]["frequency"] == nodes["dep-2"]["metrics"]["frequency"] == 5


def test_a_failing_subject_read_degrades_to_partial_and_still_200() -> None:
    api = make_api()
    api.seed(agent_doc("alpha"))
    _put(api, _point(f"agent:{agent_id('alpha')}"))
    spy = _spy(api)
    spy.fail = True
    response = api.get(ALICE, FINANCE)
    assert response.status_code == 200
    body = response.json()
    assert body["coverage"]["state"] == "partial"
    assert body["nodes"][0]["metrics"]["frequency"] is None
    assert body["nodes"][0]["metrics"]["health"] == "unknown"


def test_scope_is_checked_before_any_subject_read() -> None:
    api = make_api()
    api.seed(agent_doc("alpha"))
    spy = _spy(api)
    assert api.get(BOB, FINANCE).status_code == 403
    assert api.get(None, FINANCE).status_code == 401
    assert spy.calls == []


def test_people_and_clusters_issue_no_subject_read() -> None:
    api = make_api()
    api.seed(person_doc("0123456789abcdef"), person_doc("fedcba9876543210"))
    spy = _spy(api)
    assert api.get(ALICE, FINANCE).status_code == 200
    assert spy.calls == []
    api.limits(max_nodes=1)
    body = api.get(ALICE, FINANCE).json()
    assert {n["kind"] for n in body["nodes"]} == {"cluster"}
    assert spy.calls == []


def test_a_large_page_makes_one_bounded_read_per_kind() -> None:
    api = make_api()
    api.seed(*(agent_doc(f"a{i:04d}") for i in range(300)))
    spy = _spy(api)
    api.limits(max_nodes=2000)
    body = api.get(ALICE, FINANCE, node_budget=2000).json()
    assert len(body["nodes"]) == 300
    assert [c[2:] for c in spy.calls] == [("agent", 300)]
    assert all(c[0] == CUSTOMER and c[1] == FINANCE for c in spy.calls)


def test_a_reader_without_the_capability_keeps_unknown_metrics() -> None:
    api = make_api()
    api.seed(agent_doc("alpha"))

    class PlainReader:
        async def query(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("not used")

        async def status(self, customer_id: str) -> Any:
            return await api.store.status(customer_id)

    api.h.app.state.aggregate_reader = PlainReader()
    body = api.get(ALICE, FINANCE).json()
    assert body["nodes"][0]["metrics"]["frequency"] is None
    assert body["coverage"]["state"] == "complete"
