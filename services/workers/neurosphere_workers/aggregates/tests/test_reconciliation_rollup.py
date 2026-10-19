"""Per-source reconciliation: one reference record per request, sources reported separately."""

from __future__ import annotations

from decimal import Decimal

from neurosphere_core.aggregates import ReconciliationPoint

from .support import (
    CUST,
    DOMAIN,
    Rig,
    days_ago,
    keys,
    ledger_entry,
    observation,
    series,
    vendor_allocation,
    wide_window,
)


async def _recon(rig: Rig) -> ReconciliationPoint:
    result = await rig.aggregates.query(
        CUST, DOMAIN, "reconciliation", "day", wide_window(rig), max_series=20, max_points=720
    )
    point = series(result, "USD").points[0]
    assert isinstance(point, ReconciliationPoint)
    return point


def _source(point: ReconciliationPoint, name: str):  # type: ignore[no-untyped-def]
    return next(s for s in point.sources if s.source == name)


async def test_request_seen_by_three_sources_counts_once_in_reference() -> None:
    rig = Rig()
    at = days_ago(1)
    await rig.add_entry(
        ledger_entry(
            "req-1",
            observation("gateway", 1, "2.00", at=at),
            observation("application", 2, "2.20", at=at),
            observation("billing", 3, "2.10", at=at),
        )
    )
    assert (await rig.drain()).ok

    point = await _recon(rig)
    assert point.reference_entry_count == 1  # one request, one reference record
    assert point.reference_amount == Decimal("2.10")  # the invoice is authoritative, once
    assert [s.source for s in point.sources] == ["gateway", "app", "billing"]
    gateway, app, billing = (_source(point, n) for n in ("gateway", "app", "billing"))
    assert (gateway.amount, app.amount, billing.amount) == (
        Decimal("2.00"),
        Decimal("2.20"),
        Decimal("2.10"),
    )  # reported separately, not summed into the reference
    for source in (gateway, app, billing):
        assert source.granularity == "request"
        assert source.coverage == 1.0
        assert source.complete is True
    assert point.complete is True


async def test_source_without_observations_has_unknown_coverage_not_zero() -> None:
    rig = Rig()
    at = days_ago(1)
    await rig.add_entry(ledger_entry("req-1", observation("gateway", 1, "2.00", at=at)))
    await rig.add_entry(ledger_entry("req-2", observation("gateway", 2, "1.00", at=at)))
    assert (await rig.drain()).ok

    point = await _recon(rig)
    app, billing = _source(point, "app"), _source(point, "billing")
    for silent in (app, billing):
        assert silent.coverage is None  # unknown, not 0.0
        assert silent.amount is None
        assert silent.granularity == "unknown"
        assert silent.observed_entry_count == 0
        assert silent.complete is False
    assert _source(point, "gateway").coverage == 1.0
    assert _source(point, "gateway").amount == Decimal("3.00")


async def test_partial_source_coverage_and_unknown_amounts() -> None:
    rig = Rig()
    at = days_ago(1)
    await rig.add_entry(
        ledger_entry(
            "r1",
            observation("gateway", 1, "1.00", at=at),
            observation("application", 2, "1.00", at=at),
        )
    )
    await rig.add_entry(ledger_entry("r2", observation("gateway", 3, "1.00", at=at)))
    await rig.add_entry(ledger_entry("r3", observation("application", 4, None, at=at)))  # unknown
    await rig.add_entry(ledger_entry("r4", observation("gateway", 5, "1.00", at=at)))
    assert (await rig.drain()).ok

    point = await _recon(rig)
    assert point.reference_entry_count == 4
    gateway, app = _source(point, "gateway"), _source(point, "app")
    assert (gateway.observed_entry_count, gateway.known_count) == (3, 3)
    assert gateway.coverage == 0.75  # 3 of 4 reference requests
    assert (app.observed_entry_count, app.known_count) == (2, 1)
    assert app.coverage == 0.25
    assert app.amount == Decimal("1.00")  # known part only
    assert app.complete is False  # one of its observations is unknown
    assert point.complete is False  # r3 has no known reference amount


async def test_vendor_level_billing_is_labelled_and_kept_out_of_the_reference() -> None:
    rig = Rig()
    at = days_ago(1)
    await rig.add_entry(ledger_entry("r1", observation("gateway", 1, "2.00", at=at)))
    await rig.add_allocation(vendor_allocation(10, "50.00", at=at))
    assert (await rig.drain()).ok

    point = await _recon(rig)
    billing = _source(point, "billing")
    assert billing.granularity == "vendor"
    assert billing.allocation_count == 1
    assert billing.amount == Decimal("50.00")
    assert billing.coverage is None  # no request-level billing observation: unknown
    assert point.reference_amount == Decimal("2.00")  # request-less spend is not a request
    assert point.reference_entry_count == 1

    # An allocation-only currency still appears, with an unknown reference.
    await rig.add_allocation(vendor_allocation(11, "9.00", at=at, currency="EUR"))
    assert (await rig.drain()).ok
    result = await rig.aggregates.query(
        CUST, DOMAIN, "reconciliation", "day", wide_window(rig), max_series=20, max_points=720
    )
    assert keys(result) == ["EUR", "USD"]
    eur = series(result, "EUR").points[0]
    assert isinstance(eur, ReconciliationPoint)
    assert eur.reference_amount is None
    assert eur.reference_entry_count == 0
    assert eur.complete is False


async def test_unknown_allocation_amount_stays_unknown() -> None:
    rig = Rig()
    at = days_ago(1)
    await rig.add_allocation(vendor_allocation(10, None, at=at, currency=None))
    assert (await rig.drain()).ok
    result = await rig.aggregates.query(
        CUST, DOMAIN, "reconciliation", "day", wide_window(rig), max_series=20, max_points=720
    )
    point = series(result, "XXX").points[0]
    assert isinstance(point, ReconciliationPoint)
    billing = _source(point, "billing")
    assert billing.amount is None
    assert billing.complete is False
