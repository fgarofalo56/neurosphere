"""Azure cost export reader and billing-vs-ledger variance report (synthetic fixtures only)."""

from __future__ import annotations

import gzip
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from neurosphere_connector.testing import ConnectorContractSuite
from neurosphere_connector_azure_billing import (
    AzureBillingConnector,
    LedgerEstimate,
    aggregate_daily,
    build_variance_report,
    parse_cost_csv,
    read_export,
)
from neurosphere_core.errors import CapabilityUnavailableError, InvalidSchemaError

FIX = Path(__file__).parent / "fixtures"
AOAI = (
    "/subscriptions/s1/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/"
    "synthetic-aoai"
)
SEARCH = (
    "/subscriptions/s1/resourceGroups/rg/providers/Microsoft.Search/searchServices/synthetic-search"
)
D1, D2, D3 = date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)


class FakeSource:
    def __init__(self, manifest: bytes, blobs: dict[str, bytes]) -> None:
        self.manifest = manifest
        self.blobs = blobs
        self.reads: list[str] = []

    async def read_manifest(self) -> bytes:
        return self.manifest

    async def read_blob(self, name: str) -> bytes:
        self.reads.append(name)
        return self.blobs[name]


def _fixture_source() -> FakeSource:
    return FakeSource(
        (FIX / "manifest.json").read_bytes(),
        {
            "folder/synthetic/run/part0.csv": (FIX / "part0.csv").read_bytes(),
            "folder/synthetic/run/part1.csv": (FIX / "part1.csv").read_bytes(),
        },
    )


class TestBillingContract(ConnectorContractSuite):
    @pytest.fixture
    def connector(self) -> AzureBillingConnector:
        return AzureBillingConnector(source=_fixture_source(), basis="actual")


def test_manifest_is_advisory_daily_and_commercial_only() -> None:
    m = AzureBillingConnector(source=_fixture_source(), basis="actual").manifest
    assert m.advisory is True
    assert m.granularity.time_grain == "day"
    assert m.freshness.typical_delay_ms is None  # unknown, not 0
    assert list(m.supported_clouds) == ["commercial"]
    assert "cost_ingest" in m.capabilities


# ---- export parsing -------------------------------------------------------------------------


def test_missing_and_garbled_cost_cells_are_none_not_zero() -> None:
    rows = parse_cost_csv((FIX / "part0.csv").read_text(encoding="utf-8"), basis="actual")
    blank = next(r for r in rows if r.usage_date == D2 and r.meter_id == "meter-in")
    assert blank.cost is None
    rows1 = parse_cost_csv((FIX / "part1.csv").read_text(encoding="utf-8"), basis="actual")
    by_meter = {r.meter_id: r.cost for r in rows1}
    assert by_meter["meter-in"] == Decimal("0.00")  # explicit zero stays zero
    assert by_meter["meter-in"] is not None
    assert by_meter["meter-out"] is None  # garbled is unknown, not 0


def test_missing_cost_column_entirely_gives_none_costs() -> None:
    rows = parse_cost_csv("Date,ResourceId\n2026-09-01,/r1\n", basis="actual")
    assert [r.cost for r in rows] == [None]


def test_unusable_schema_is_rejected() -> None:
    with pytest.raises(InvalidSchemaError):
        parse_cost_csv("Foo,Bar\n1,2\n", basis="actual")


def test_header_aliases_bom_and_us_dates() -> None:
    text = "\ufeffUsageDate,PreTaxCost,Currency,InstanceId\n09/01/2026,2.5,usd,/r1\n"
    (row,) = parse_cost_csv(text, basis="amortized")
    assert (row.usage_date, row.cost, row.currency, row.resource_id) == (
        D1,
        Decimal("2.5"),
        "USD",
        "/r1",
    )
    assert row.basis == "amortized"


async def test_read_export_reports_counts_and_completeness() -> None:
    result = await read_export(_fixture_source(), basis="actual")
    assert result.rows_read == 7
    assert result.complete is True
    assert result.rows_with_unknown_cost == 2
    assert result.rows_with_bad_cost == 1
    assert result.blobs_read == result.blobs_expected == 2
    assert result.manifest_type == "SyntheticFixture"  # recorded verbatim, not interpreted
    assert "day per resource per meter" in result.granularity


async def test_incomplete_export_is_flagged_not_hidden() -> None:
    manifest = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
    manifest["dataRowCount"] = 99
    src = _fixture_source()
    src.manifest = json.dumps(manifest).encode()
    result = await read_export(src, basis="actual")
    assert result.complete is False


async def test_gzip_partitions_are_read() -> None:
    manifest = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
    manifest["deliveryConfig"]["compressionMode"] = "Gzip"
    manifest["blobs"] = manifest["blobs"][:1]
    manifest["dataRowCount"] = 5
    src = FakeSource(
        json.dumps(manifest).encode(),
        {"folder/synthetic/run/part0.csv": gzip.compress((FIX / "part0.csv").read_bytes())},
    )
    assert (await read_export(src, basis="actual")).rows_read == 5


async def test_parquet_is_unavailable_not_silently_empty() -> None:
    manifest = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
    manifest["deliveryConfig"]["fileFormat"] = "Parquet"
    src = FakeSource(json.dumps(manifest).encode(), {})
    with pytest.raises(CapabilityUnavailableError):
        await read_export(src, basis="actual")


async def test_bad_manifest_rejected() -> None:
    with pytest.raises(InvalidSchemaError):
        await read_export(FakeSource(b"not json", {}), basis="actual")
    with pytest.raises(InvalidSchemaError):
        await read_export(FakeSource(b'{"no":"blobs"}', {}), basis="actual")


# ---- aggregation ----------------------------------------------------------------------------


async def test_aggregates_keep_export_granularity_and_null() -> None:
    export = await read_export(_fixture_source(), basis="actual")
    aggs = aggregate_daily(export.rows)
    # Meters are not merged: day 1 has aoai in, aoai out and search -> 3 aggregates.
    day1 = [a for a in aggs if a.usage_date == D1]
    assert len(day1) == 3
    assert {a.meter_id for a in day1} == {"meter-in", "meter-out", "meter-unit"}
    unknown = next(a for a in aggs if a.usage_date == D2 and a.meter_id == "meter-in")
    assert unknown.cost is None and unknown.null_cost_rows == 1


def test_any_unknown_contributor_makes_the_aggregate_unknown() -> None:
    text = "Date,ResourceId,MeterId,BillingCurrencyCode,CostInBillingCurrency\n"
    text += "2026-09-01,/r,m,USD,1.00\n2026-09-01,/r,m,USD,\n"
    (agg,) = aggregate_daily(parse_cost_csv(text, basis="actual"))
    assert agg.cost is None  # not the 1.00 lower bound, and not 0
    assert (agg.row_count, agg.null_cost_rows) == (2, 1)


def test_basis_kind_and_currency_never_merge() -> None:
    base = "Date,ResourceId,MeterId,BillingCurrencyCode,CostInBillingCurrency\n"
    a = parse_cost_csv(base + "2026-09-01,/r,m,USD,1\n", basis="actual", amount_kind="estimated")
    b = parse_cost_csv(base + "2026-09-01,/r,m,USD,2\n", basis="actual", amount_kind="invoiced")
    c = parse_cost_csv(base + "2026-09-01,/r,m,USD,3\n", basis="amortized")
    d = parse_cost_csv(base + "2026-09-01,/r,m,EUR,4\n", basis="actual")
    aggs = aggregate_daily([*a, *b, *c, *d])
    assert len(aggs) == 4
    assert {(g.basis, g.amount_kind, g.currency): g.cost for g in aggs} == {
        ("actual", "estimated", "USD"): Decimal(1),
        ("actual", "invoiced", "USD"): Decimal(2),
        ("amortized", "estimated", "USD"): Decimal(3),
        ("actual", "estimated", "EUR"): Decimal(4),
    }


def test_export_defaults_to_estimated_not_invoiced() -> None:
    (row,) = parse_cost_csv("Date,CostInBillingCurrency\n2026-09-01,1\n", basis="actual")
    assert row.amount_kind == "estimated"


# ---- connector ------------------------------------------------------------------------------


async def test_connector_read_reports_coverage_and_unknown_lag() -> None:
    c = AzureBillingConnector(source=_fixture_source(), basis="actual")
    result = await c.read()
    assert len(result.aggregates) == 7  # every row is a distinct day/resource/meter
    cov = await c.coverage()
    assert (cov.expected_sources, cov.answered_sources, cov.partial) == (2, 2, False)
    fresh = await c.freshness()
    assert fresh.lag_ms is None


# ---- variance -------------------------------------------------------------------------------


async def _aggs():
    return aggregate_daily((await read_export(_fixture_source(), basis="actual")).rows)


async def test_variance_at_source_granularity_states_it_and_nulls_stay_null() -> None:
    estimates = [
        LedgerEstimate(usage_date=D1, resource_id=AOAI, currency="USD", amount=Decimal("3.50")),
        LedgerEstimate(usage_date=D2, resource_id=AOAI, currency="USD", amount=Decimal("3.00")),
        LedgerEstimate(usage_date=date(2026, 9, 9), resource_id=AOAI, currency="USD"),
    ]
    report = build_variance_report(await _aggs(), estimates, level="day_resource")
    assert report.comparison_level == "day_resource"
    assert "daily rows per resource per meter" in report.granularity_statement
    assert "Nothing is apportioned below the billing granularity" in report.granularity_statement
    assert "day per resource per meter" in report.billing_granularity

    by = {(ln.usage_date, ln.resource_id): ln for ln in report.lines}
    d1 = by[(D1, AOAI)]
    assert d1.status == "compared"
    assert d1.billing_amount == Decimal("3.75")
    assert d1.variance == Decimal("0.25")
    assert d1.variance_ratio is not None and round(d1.variance_ratio, 4) == Decimal("0.0714")

    d2 = by[(D2, AOAI)]  # one meter has a blank cost -> billing unknown, variance unknown
    assert d2.status == "billing_unknown"
    assert d2.billing_amount is None and d2.variance is None and d2.variance_ratio is None

    d3 = by[(D3, AOAI)]  # no estimate exists: unknown, not zero
    assert d3.status == "no_estimate"
    assert d3.estimate_amount is None and d3.variance is None

    assert by[(D1, SEARCH)].status == "no_estimate"
    assert [(u.usage_date, u.amount) for u in report.unmatched_estimates] == [
        (date(2026, 9, 9), None)
    ]


async def test_variance_day_level_rolls_up_billing_only() -> None:
    estimates = [LedgerEstimate(usage_date=D1, currency="USD", amount=Decimal("10"))]
    report = build_variance_report(await _aggs(), estimates, level="day")
    assert report.comparison_level == "day"
    assert "all resources" in report.granularity_statement
    d1 = next(ln for ln in report.lines if ln.usage_date == D1)
    assert d1.resource_id is None
    assert d1.billing_amount == Decimal("7.75")  # 1.50 + 2.25 + 4.00, billing only
    assert d1.variance == Decimal("-2.25")


async def test_report_never_sums_billing_with_estimates() -> None:
    aggs = await _aggs()
    lo = [LedgerEstimate(usage_date=D1, resource_id=AOAI, currency="USD", amount=Decimal("1"))]
    hi = [LedgerEstimate(usage_date=D1, resource_id=AOAI, currency="USD", amount=Decimal("900"))]
    a = build_variance_report(aggs, lo).lines
    b = build_variance_report(aggs, hi).lines
    la = next(ln for ln in a if ln.usage_date == D1 and ln.resource_id == AOAI)
    lb = next(ln for ln in b if ln.usage_date == D1 and ln.resource_id == AOAI)
    assert la.billing_amount == lb.billing_amount == Decimal("3.75")
    assert la.estimate_amount == Decimal(1) and lb.estimate_amount == Decimal(900)
    notes = " ".join(build_variance_report(aggs, lo).notes)
    assert "never summed" in notes


async def test_estimate_unknown_and_both_unknown_and_zero_estimate() -> None:
    aggs = await _aggs()
    est = [
        LedgerEstimate(usage_date=D1, resource_id=AOAI, currency="USD", amount=None),
        LedgerEstimate(usage_date=D2, resource_id=AOAI, currency="USD", amount=None),
        LedgerEstimate(usage_date=D1, resource_id=SEARCH, currency="USD", amount=Decimal(0)),
    ]
    lines = {(ln.usage_date, ln.resource_id): ln for ln in build_variance_report(aggs, est).lines}
    assert lines[(D1, AOAI)].status == "estimate_unknown"
    assert lines[(D1, AOAI)].variance is None
    assert lines[(D2, AOAI)].status == "both_unknown"
    zero = lines[(D1, SEARCH)]
    assert zero.status == "compared" and zero.variance == Decimal("4.00")
    assert zero.variance_ratio is None  # no division by a zero estimate


async def test_currency_mismatch_is_not_compared() -> None:
    est = [LedgerEstimate(usage_date=D1, resource_id=AOAI, currency="EUR", amount=Decimal("3"))]
    line = next(
        ln
        for ln in build_variance_report(await _aggs(), est).lines
        if ln.usage_date == D1 and ln.resource_id == AOAI
    )
    assert line.status == "currency_mismatch"
    assert line.variance is None


async def test_estimated_and_invoiced_billing_stay_separate_lines() -> None:
    base = "Date,ResourceId,MeterId,BillingCurrencyCode,CostInBillingCurrency\n"
    rows = [
        *parse_cost_csv(base + "2026-09-01,/r,m,USD,5\n", basis="actual", amount_kind="estimated"),
        *parse_cost_csv(base + "2026-09-01,/r,m,USD,6\n", basis="actual", amount_kind="invoiced"),
    ]
    est = [LedgerEstimate(usage_date=D1, resource_id="/r", currency="USD", amount=Decimal(4))]
    report = build_variance_report(aggregate_daily(rows), est)
    kinds = {ln.billing_amount_kind: ln.variance for ln in report.lines}
    assert kinds == {"estimated": Decimal(1), "invoiced": Decimal(2)}


async def test_other_basis_is_excluded_and_counted() -> None:
    base = "Date,ResourceId,MeterId,BillingCurrencyCode,CostInBillingCurrency\n"
    rows = [
        *parse_cost_csv(base + "2026-09-01,/r,m,USD,5\n", basis="actual"),
        *parse_cost_csv(base + "2026-09-01,/r,m,USD,7\n", basis="amortized"),
    ]
    report = build_variance_report(aggregate_daily(rows), [], basis="actual")
    assert report.billing_rows_other_basis_ignored == 1
    assert [ln.billing_amount for ln in report.lines] == [Decimal(5)]


def test_resource_id_match_is_case_insensitive() -> None:
    rows = parse_cost_csv(
        "Date,ResourceId,BillingCurrencyCode,CostInBillingCurrency\n2026-09-01,/R1,USD,2\n",
        basis="actual",
    )
    est = [LedgerEstimate(usage_date=D1, resource_id="/r1", currency="USD", amount=Decimal(1))]
    (line,) = build_variance_report(aggregate_daily(rows), est).lines
    assert line.status == "compared" and line.variance == Decimal(1)
