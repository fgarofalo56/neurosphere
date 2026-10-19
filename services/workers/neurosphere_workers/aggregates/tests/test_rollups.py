"""Rollups from the outbox: cost series, latency, errors, coverage parity, grains, 90-day window."""

from __future__ import annotations

import subprocess
import sys
from datetime import date
from decimal import Decimal

import pytest
from neurosphere_core.aggregates import (
    HOUR_RETENTION_DAYS,
    CostPoint,
    CoveragePoint,
    ErrorPoint,
    LatencyPoint,
)
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.ledger import compute_totals

from .support import (
    CUST,
    DOMAIN,
    NOW,
    Rig,
    days_ago,
    event_doc,
    keys,
    ledger_entry,
    observation,
    series,
    wide_window,
)


async def _query(rig: Rig, metric: str, grain: str = "day", **bounds: int):  # type: ignore[no-untyped-def]
    return await rig.aggregates.query(
        CUST,
        DOMAIN,
        metric,  # type: ignore[arg-type]
        grain,  # type: ignore[arg-type]
        wide_window(rig, 13 if grain == "hour" else 90),
        max_series=bounds.get("max_series", 20),
        max_points=bounds.get("max_points", 720),
    )


async def test_estimated_and_invoiced_are_separate_series_with_price_version() -> None:
    rig = Rig()
    at = days_ago(1)
    # req-1: gateway estimate + billing invoice (one request, two observations).
    await rig.add_entry(
        ledger_entry(
            "req-1",
            observation("gateway", 1, "2.50", at=at),
            observation("billing", 2, "3.00", at=at),
        )
    )
    await rig.add_entry(ledger_entry("req-2", observation("gateway", 3, "1.25", at=at)))
    assert (await rig.drain()).ok

    result = await _query(rig, "cost")
    assert keys(result) == ["estimated:USD", "invoiced:USD"]  # never a blended series
    estimated = series(result, "estimated:USD").points[0]
    invoiced = series(result, "invoiced:USD").points[0]
    assert isinstance(estimated, CostPoint)
    assert isinstance(invoiced, CostPoint)
    assert estimated.amount == Decimal("3.75")
    assert estimated.kind == "estimated"
    assert estimated.complete is True
    assert invoiced.amount == Decimal("3.00")
    assert invoiced.entry_count == 1  # req-2 has no invoice: not part of that series
    assert [(p.id, p.effective_date) for p in estimated.price_versions] == [
        ("pv-1", date(2026, 1, 1))
    ]
    assert invoiced.price_versions == []  # an invoice cites no price version


async def test_cost_is_per_currency_never_summed_across() -> None:
    rig = Rig()
    at = days_ago(1)
    await rig.add_entry(ledger_entry("r1", observation("billing", 1, "4.00", at=at)))
    await rig.add_entry(
        ledger_entry("r2", observation("billing", 2, "5.00", at=at, currency="EUR"))
    )
    assert (await rig.drain()).ok
    result = await _query(rig, "cost")
    assert keys(result) == ["invoiced:EUR", "invoiced:USD"]
    assert series(result, "invoiced:EUR").points[0].amount == Decimal("5.00")  # type: ignore[union-attr]
    assert series(result, "invoiced:USD").points[0].amount == Decimal("4.00")  # type: ignore[union-attr]


async def test_latency_percentiles_and_error_rate() -> None:
    rig = Rig()
    at = days_ago(1)
    for i in range(1, 11):  # durations 100..1000 ms
        outcome = "error" if i in (9, 10) else "success"
        await rig.add_event(event_doc(f"e{i}", at=at, duration_ms=i * 100, outcome=outcome))
    # A non model_call span is not counted.
    await rig.add_event(event_doc("tool", at=at, duration_ms=5, span_kind="tool_call"))
    assert (await rig.drain()).ok

    latency = (await _query(rig, "latency")).series[0].points[0]
    errors = (await _query(rig, "errors")).series[0].points[0]
    assert isinstance(latency, LatencyPoint)
    assert isinstance(errors, ErrorPoint)
    assert (latency.p50_ms, latency.p95_ms, latency.p99_ms) == (500, 1000, 1000)
    assert latency.sample_count == 10
    assert latency.complete is True
    assert errors.request_count == 10
    assert errors.error_count == 2
    assert errors.error_rate == pytest.approx(0.2)


async def test_coverage_matches_ledger_totals_semantics() -> None:
    rig = Rig()
    at = days_ago(1)
    entries = [
        ledger_entry("c1", observation("gateway", 1, "1.00", at=at)),
        ledger_entry("c2", observation("gateway", 2, "2.00", at=at)),
        ledger_entry("c3", observation("gateway", 3, None, at=at, unresolved=True)),  # unresolved
        ledger_entry("c4", observation("gateway", 4, "9.00", at=at, currency="EUR")),
        ledger_entry("c5", observation("gateway", 5, None, at=at)),  # unknown tokens
    ]
    for entry in entries:
        await rig.add_entry(entry)
    assert (await rig.drain()).ok

    expected = compute_totals(entries)
    result = await _query(rig, "coverage")
    assert keys(result) == sorted(expected)
    for currency, total in expected.items():
        point = series(result, currency).points[0]
        assert isinstance(point, CoveragePoint)
        assert point.entry_count == total.entry_count
        assert point.known_count == total.known_count
        assert point.unresolved_count == total.unresolved_count
        assert point.unknown_count == total.unknown_count
        assert point.amount == total.amount
        assert point.coverage == pytest.approx(total.coverage)
        assert point.complete == total.complete


async def test_day_and_hour_grains_and_hour_is_bounded() -> None:
    rig = Rig()
    recent = days_ago(2, hour=9)
    old = days_ago(HOUR_RETENTION_DAYS + 5, hour=9)
    await rig.add_entry(ledger_entry("recent", observation("gateway", 1, "1.00", at=recent)))
    await rig.add_entry(ledger_entry("old", observation("gateway", 2, "2.00", at=old)))
    assert (await rig.drain()).ok

    days = await _query(rig, "cost")
    assert len(series(days, "estimated:USD").points) == 2  # both days materialized
    hours = await _query(rig, "cost", "hour")
    points = series(hours, "estimated:USD").points
    assert [p.bucket_start for p in points] == [recent.strftime("%Y-%m-%dT09:00:00Z")]
    # The hour grain refuses a window wider than its retention.
    with pytest.raises(InvalidSchemaError):
        await rig.aggregates.query(
            CUST, DOMAIN, "cost", "hour", wide_window(rig, 30), max_series=1, max_points=1
        )


async def test_records_older_than_90_days_fall_out_of_the_window() -> None:
    rig = Rig()
    await rig.add_entry(ledger_entry("in", observation("gateway", 1, "1.00", at=days_ago(89))))
    await rig.add_entry(ledger_entry("out", observation("gateway", 2, "7.00", at=days_ago(91))))
    assert (await rig.drain()).ok
    points = series(await _query(rig, "cost", max_points=2160), "estimated:USD").points
    assert [p.amount for p in points] == [Decimal("1.00")]  # type: ignore[union-attr]
    assert rig.projection.stats.dropped_out_of_window == 1

    # Time passes: the first record leaves the window on the next prune and rebuild.
    rig.now = days_ago(-2)
    assert await rig.projection.prune(CUST) > 0
    assert rig.aggregates.documents(CUST) == {}


async def test_changed_entry_moves_between_buckets_without_double_counting() -> None:
    rig = Rig()
    first = ledger_entry("req", observation("gateway", 1, "2.00", at=days_ago(3)))
    await rig.add_entry(first)
    assert (await rig.drain()).ok
    # A billing observation arrives from an EARLIER day: the entry's occurred_at moves.
    second = ledger_entry(
        "req",
        observation("gateway", 1, "2.00", at=days_ago(3)),
        observation("billing", 2, "2.10", at=days_ago(5)),
    )
    await rig.ledger_store.write_entry(
        second,
        (await rig.ledger_store.read_entry(CUST, first.id)).version,  # type: ignore[union-attr]
    )
    from .support import entry_pointer

    await rig.outbox.append(entry_pointer(second))
    assert (await rig.drain()).ok

    estimated = series(await _query(rig, "cost"), "estimated:USD").points
    assert [(p.bucket_start[:10], p.amount) for p in estimated] == [
        (days_ago(5).strftime("%Y-%m-%d"), Decimal("2.00"))
    ]  # exactly one contribution, in the new bucket only


async def test_series_and_point_bounds_report_truncation() -> None:
    rig = Rig()
    for day in range(1, 6):
        await rig.add_entry(
            ledger_entry(f"r{day}", observation("gateway", day, "1.00", at=days_ago(day)))
        )
    await rig.add_entry(
        ledger_entry("eur", observation("billing", 99, "1.00", at=days_ago(1), currency="EUR"))
    )
    assert (await rig.drain()).ok

    one_series = await _query(rig, "cost", max_series=1)
    assert one_series.truncated is True
    assert len(one_series.series) == 1
    two_points = await _query(rig, "cost", max_points=2)
    est = series(two_points, "estimated:USD")
    assert two_points.truncated is True
    assert len(est.points) == 2
    assert est.points[-1].bucket_start[:10] == days_ago(1).strftime("%Y-%m-%d")  # newest kept
    for bad_series, bad_points in ((0, 5), (5, 0), (5, 5000), (51, 5)):
        with pytest.raises(InvalidSchemaError):
            await rig.aggregates.query(
                CUST,
                DOMAIN,
                "cost",
                "day",
                wide_window(rig),
                max_series=bad_series,
                max_points=bad_points,
            )


async def test_status_exposes_watermark_for_lag() -> None:
    rig = Rig()
    at = days_ago(0.25)
    await rig.add_entry(ledger_entry("r", observation("billing", 1, "1.00", at=at)))
    assert (await rig.drain()).ok
    status = await rig.aggregates.status(CUST)
    assert status is not None
    assert status.watermark is not None
    assert status.billing_observed_at is not None
    assert status.lag_seconds(NOW) == pytest.approx(0.25 * 86_400, abs=1)
    doc = series(await _query(rig, "cost"), "invoiced:USD").points[0]
    assert doc.watermark == status.watermark


def test_worker_modules_import_with_the_analytics_package_blocked() -> None:
    """Acceptance 1 (part): the worker and the Cosmos store never import the analytics adapter.

    A clean interpreter in which ``neurosphere_core.analytics`` cannot be imported still imports
    both, so an analytics outage cannot affect them.
    """
    code = (
        "import sys; sys.modules['neurosphere_core.analytics'] = None; "
        "import neurosphere_workers.aggregates, neurosphere_core.aggregates.cosmos; print('ok')"
    )
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr


async def test_aggregates_update_and_read_while_analytics_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance 1 (part): with the analytics package unimportable, drain and read still work."""
    monkeypatch.setitem(sys.modules, "neurosphere_core.analytics", None)
    rig = Rig()
    await rig.add_entry(ledger_entry("r", observation("gateway", 1, "1.00", at=days_ago(1))))
    assert (await rig.drain()).ok
    assert series(await _query(rig, "cost"), "estimated:USD").points
