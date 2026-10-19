"""Unknown is never 0 (NS-01): null-heavy fixtures through the full outbox -> aggregate path."""

from __future__ import annotations

from decimal import Decimal

import pytest
from neurosphere_core.aggregates import CostPoint, CoveragePoint, ErrorPoint, LatencyPoint

from neurosphere_workers.aggregates import known_sum, percentile

from .support import (
    CUST,
    DOMAIN,
    Rig,
    days_ago,
    event_doc,
    ledger_entry,
    observation,
    series,
    wide_window,
)


async def _read(rig: Rig, metric: str):  # type: ignore[no-untyped-def]
    return await rig.aggregates.query(
        CUST,
        DOMAIN,
        metric,  # type: ignore[arg-type]
        "day",
        wide_window(rig),
        max_series=20,
        max_points=720,
    )


def test_known_sum_never_coerces_none_to_zero() -> None:
    assert known_sum([]) is None
    assert known_sum([None, None]) is None
    assert known_sum([None, Decimal("1.50"), None, Decimal("2.25")]) == Decimal("3.75")
    assert known_sum([Decimal("0")]) == Decimal("0")  # a measured zero stays a zero


@pytest.mark.parametrize("values", [[], [7], [1, 2, 3, 4]])
def test_percentile_of_nothing_is_none(values: list[int]) -> None:
    assert (percentile(values, 50) is None) == (not values)


async def test_partially_unknown_cost_keeps_known_sum_and_is_not_complete() -> None:
    rig = Rig()
    at = days_ago(1)
    await rig.add_entry(ledger_entry("k1", observation("gateway", 1, "1.00", at=at)))
    await rig.add_entry(ledger_entry("k2", observation("gateway", 2, "2.00", at=at)))
    await rig.add_entry(ledger_entry("u1", observation("gateway", 3, None, at=at)))  # tokens?
    await rig.add_entry(ledger_entry("u2", observation("gateway", 4, None, at=at, unresolved=True)))
    assert (await rig.drain()).ok

    result = await _read(rig, "cost")
    usd = series(result, "estimated:USD").points[0]
    assert isinstance(usd, CostPoint)
    assert usd.amount == Decimal("3.00")  # the known parts, not a silently smaller "total"
    assert usd.complete is False
    assert (usd.known_count, usd.entry_count) == (2, 4)  # unattributed unknowns count against it

    unattributed = series(result, "estimated:XXX").points[0]
    assert isinstance(unattributed, CostPoint)
    assert unattributed.amount is None  # all unknown: value None, never 0
    assert unattributed.complete is False
    assert unattributed.known_count == 0
    assert unattributed.model_dump(mode="json")["amount"] is None


async def test_all_unknown_cost_and_coverage() -> None:
    rig = Rig()
    at = days_ago(1)
    await rig.add_entry(ledger_entry("u1", observation("billing", 1, None, at=at)))
    await rig.add_entry(ledger_entry("u2", observation("billing", 2, None, at=at)))
    assert (await rig.drain()).ok

    cost = (await _read(rig, "cost")).series
    assert [s.key for s in cost] == ["invoiced:XXX"]
    only = cost[0].points[0]
    assert isinstance(only, CostPoint)
    assert only.amount is None
    assert only.complete is False

    cov = series(await _read(rig, "coverage"), "XXX").points[0]
    assert isinstance(cov, CoveragePoint)
    assert cov.amount is None
    assert cov.known_count == 0
    assert cov.complete is False


async def test_latency_with_missing_durations() -> None:
    rig = Rig()
    at = days_ago(1)
    await rig.add_event(event_doc("a", at=at, duration_ms=200))
    await rig.add_event(event_doc("b", at=at, duration_ms=None))  # unknown, not 0 ms
    assert (await rig.drain()).ok
    point = (await _read(rig, "latency")).series[0].points[0]
    assert isinstance(point, LatencyPoint)
    assert (point.sample_count, point.missing_count) == (1, 1)
    assert point.p50_ms == 200  # the unknown did not drag the percentile toward 0
    assert point.complete is False


async def test_latency_with_no_durations_is_none() -> None:
    rig = Rig()
    await rig.add_event(event_doc("a", at=days_ago(1), duration_ms=None))
    assert (await rig.drain()).ok
    point = (await _read(rig, "latency")).series[0].points[0]
    assert isinstance(point, LatencyPoint)
    assert (point.p50_ms, point.p95_ms, point.p99_ms) == (None, None, None)
    assert point.sample_count == 0
    assert point.complete is False


async def test_errors_with_unknown_outcomes() -> None:
    rig = Rig()
    at = days_ago(1)
    await rig.add_event(event_doc("a", at=at, duration_ms=1, outcome="unknown"))
    await rig.add_event(event_doc("b", at=at, duration_ms=1, outcome=None))
    assert (await rig.drain()).ok
    point = (await _read(rig, "errors")).series[0].points[0]
    assert isinstance(point, ErrorPoint)
    assert point.error_count is None  # nothing known: unknown, never "0 errors"
    assert point.error_rate is None
    assert point.unknown_count == 2
    assert point.complete is False

    await rig.add_event(event_doc("c", at=at, duration_ms=1, outcome="success"))
    assert (await rig.drain()).ok
    mixed = (await _read(rig, "errors")).series[0].points[0]
    assert isinstance(mixed, ErrorPoint)
    assert (mixed.error_count, mixed.request_count, mixed.error_rate) == (0, 1, 0.0)
    assert mixed.complete is False  # a measured zero, but two spans are still unknown
