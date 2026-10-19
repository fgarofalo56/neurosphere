"""NS-01 at the API boundary: unknown is null/unknown and never 0; a real 0 is a known 0; a total
over partly unknown points is the known sum with ``complete: false``."""

from datetime import date
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st
from neurosphere_core.aggregates import AggregateSeries, PriceVersionRef, QueryResult

from neurosphere_api.dashboards.mapping import map_result
from neurosphere_api.dashboards.models import MetricValue
from neurosphere_api.dashboards.tests.support import (
    ALICE,
    FINANCE,
    cost_point,
    coverage_point,
    error_point,
    latency_point,
    make_api,
)

amounts = st.one_of(st.none(), st.decimals(min_value=0, max_value=10_000, places=2))
ints = st.one_of(st.none(), st.integers(min_value=0, max_value=60_000))


def _assert_pair(value: MetricValue) -> None:
    assert (value.status == "unknown") == (value.value is None)


@settings(max_examples=60, deadline=None)
@given(st.lists(amounts, min_size=1, max_size=12))
def test_cost_points_and_total_over_nullable_amounts(raw: list[Decimal | None]) -> None:
    points = tuple(cost_point(FINANCE, i, None if a is None else str(a)) for i, a in enumerate(raw))
    mapped = map_result(
        "cost",
        QueryResult(series=(AggregateSeries(key="estimated:USD", points=points),), truncated=False),
    )
    (series,) = mapped.series
    for point in series.points:
        _assert_pair(point.value)
    by_t = {p.t: p.value for p in series.points}
    for source, amount in zip(points, raw, strict=True):
        got = by_t[source.bucket_start]
        if amount is None:
            assert got.value is None
            assert got.status == "unknown"
        else:
            assert got.status == "known"
            assert got.value == float(amount)  # a genuine 0 stays 0
    known = [a for a in raw if a is not None]
    if not known:
        assert series.total.status == "unknown"
        assert series.total.value is None
        assert series.total.complete is False
    else:
        assert series.total.status == "known"
        assert series.total.value == float(sum(known, Decimal(0)))
        assert series.total.complete is (len(known) == len(raw))


@settings(max_examples=40, deadline=None)
@given(ints, ints, ints)
def test_latency_percentiles_unknown_not_zero(
    p50: int | None, p95: int | None, p99: int | None
) -> None:
    point = latency_point(FINANCE, 1, p50, p95, p99)
    mapped = map_result(
        "latency",
        QueryResult(series=(AggregateSeries(key="latency", points=(point,)),), truncated=False),
    )
    assert [s.key for s in mapped.series] == ["p50", "p95", "p99"]
    for series, raw in zip(mapped.series, (p50, p95, p99), strict=True):
        (only,) = series.points
        _assert_pair(only.value)
        assert only.value.value == (None if raw is None else float(raw))
        assert series.total.status == "unknown"  # percentiles do not combine across buckets


@settings(max_examples=40, deadline=None)
@given(
    st.lists(st.one_of(st.none(), st.integers(min_value=0, max_value=50)), min_size=1, max_size=8)
)
def test_error_count_total_is_known_sum_and_incomplete_when_partial(
    counts: list[int | None],
) -> None:
    points = tuple(
        error_point(FINANCE, i, c, 100, None if c is None else c / 100)
        for i, c in enumerate(counts)
    )
    mapped = map_result(
        "errors",
        QueryResult(series=(AggregateSeries(key="errors", points=points),), truncated=False),
    )
    rate, count = mapped.series
    assert (rate.key, count.key) == ("error_rate", "error_count")
    known = [c for c in counts if c is not None]
    if not known:
        assert count.total.status == "unknown"
        assert rate.total.status == "unknown"
    else:
        assert count.total.value == float(sum(known))
        assert count.total.complete is (len(known) == len(counts))
    for p in count.points:
        _assert_pair(p.value)
    for p in rate.points:
        _assert_pair(p.value)


def test_coverage_zero_is_known_and_unknown_is_null() -> None:
    zero = coverage_point(FINANCE, 1, 0, 5, 0.0)
    unknown = coverage_point(FINANCE, 2, 0, 0, None)
    mapped = map_result(
        "coverage",
        QueryResult(series=(AggregateSeries(key="USD", points=(unknown, zero)),), truncated=False),
    )
    (series,) = mapped.series
    values = {p.t: p.value for p in series.points}
    assert values[zero.bucket_start].value == 0.0
    assert values[zero.bucket_start].status == "known"
    assert values[unknown.bucket_start].value is None
    assert values[unknown.bucket_start].status == "unknown"
    assert series.total.complete is False


def test_endpoint_serializes_null_not_zero_and_flags_partial_total() -> None:
    api = make_api()
    api.seed(
        cost_point(FINANCE, 1, "12.50"),
        cost_point(FINANCE, 2, None),
        cost_point(FINANCE, 3, "0"),
    )
    response = api.get(ALICE, FINANCE, "cost", days=7)
    assert response.status_code == 200, response.text
    body = response.json()
    (series,) = body["series"]
    by_value = [p["value"] for p in series["points"]]
    assert {
        "value": None,
        "status": "unknown",
        "complete": False,
        "price_version": None,
    } in by_value
    assert any(v["value"] == 0.0 and v["status"] == "known" for v in by_value)
    assert series["total"]["value"] == 12.5
    assert series["total"]["complete"] is False
    assert body["complete"] is False


def test_all_unknown_total_is_unknown_over_the_wire() -> None:
    api = make_api()
    api.seed(cost_point(FINANCE, 1, None), cost_point(FINANCE, 2, None))
    body = api.get(ALICE, FINANCE, "cost", days=7).json()
    assert body["series"][0]["total"] == {
        "value": None,
        "status": "unknown",
        "complete": False,
        "price_version": None,
    }


def test_price_versions_carry_id_and_effective_date_and_unresolved_is_incomplete() -> None:
    api = make_api()
    resolved = PriceVersionRef(id="pv-1", effective_date=date(2026, 9, 1))
    unresolved = PriceVersionRef(id="pv-2", effective_date=None)
    api.seed(
        cost_point(FINANCE, 1, "3.00", versions=(resolved,)),
        cost_point(FINANCE, 2, "4.00", versions=(unresolved,)),
    )
    body = api.get(ALICE, FINANCE, "cost", days=7).json()
    assert body["price_versions"] == [{"id": "pv-1", "effective_date": "2026-09-01"}]
    (series,) = body["series"]
    assert series["total"]["price_version"] == {"id": "pv-1", "effective_date": "2026-09-01"}
    flags = sorted(p["value"]["complete"] for p in series["points"])
    assert flags == [False, True]
    assert series["total"]["complete"] is False


def test_estimated_and_invoiced_are_separate_series_never_blended() -> None:
    api = make_api()
    api.seed(
        cost_point(FINANCE, 1, "10", kind="estimated"),
        cost_point(FINANCE, 1, "11", kind="invoiced"),
        cost_point(FINANCE, 1, "5", kind="estimated", currency="EUR"),
    )
    body = api.get(ALICE, FINANCE, "cost", days=7).json()
    got = {(s["kind"], s["currency"]): s["total"]["value"] for s in body["series"]}
    assert got == {("estimated", "USD"): 10.0, ("invoiced", "USD"): 11.0, ("estimated", "EUR"): 5.0}


def test_freshness_null_watermark_is_null_lag_not_zero() -> None:
    api = make_api()
    body = api.get(ALICE, FINANCE, "cost").json()
    assert body["freshness"] == {
        "watermark": None,
        "lag_seconds": None,
        "billing_source_freshness": None,
    }
    assert body["complete"] is False
    assert body["series"] == []
