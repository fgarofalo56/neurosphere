"""Reader hardening from the item-5 review (PRP-09 r2 item 12). Synthetic data only."""

from __future__ import annotations

import gzip
import json
from datetime import date
from decimal import Decimal

import pytest
from neurosphere_connector_azure_billing import (
    AzureBillingConnector,
    BillingAggregate,
    ExportBlobNotFoundError,
    build_variance_report,
    parse_cost_csv,
    read_export,
)
from neurosphere_core.errors import InvalidSchemaError

HEADER = "Date,CostInBillingCurrency,BillingCurrencyCode,ResourceId,MeterId\n"
PART = "folder/run/part0.csv"


class FakeSource:
    def __init__(self, manifest: dict[str, object], blobs: dict[str, bytes]) -> None:
        self.manifest = json.dumps(manifest).encode()
        self.blobs = blobs

    async def read_manifest(self) -> bytes:
        return self.manifest

    async def read_blob(self, name: str) -> bytes:
        if name not in self.blobs:
            raise ExportBlobNotFoundError(name)
        return self.blobs[name]


def _manifest(blobs: list[str], *, compression: str = "None", **extra: object) -> dict[str, object]:
    return {
        "blobCount": len(blobs),
        "deliveryConfig": {"fileFormat": "Csv", "compressionMode": compression},
        "blobs": [{"blobName": b} for b in blobs],
        **extra,
    }


async def test_gzip_bomb_is_refused_with_a_typed_error() -> None:
    bomb = gzip.compress(HEADER.encode() + b"x" * 50_000)
    src = FakeSource(_manifest([PART], compression="Gzip"), {PART: bomb})
    with pytest.raises(InvalidSchemaError) as caught:
        await read_export(src, basis="actual", max_decompressed_bytes=10_000)
    assert caught.value.reason == "export_too_large"


async def test_gzip_under_the_cap_and_multi_member_are_read() -> None:
    one = HEADER + "2026-09-01,1.5,USD,/r1,m1\n"
    two = "2026-09-02,2.5,USD,/r1,m1\n"
    data = gzip.compress(one.encode()) + gzip.compress(two.encode())
    src = FakeSource(_manifest([PART], compression="Gzip"), {PART: data})
    result = await read_export(src, basis="actual")
    assert result.rows_read == 2


async def test_truncated_or_invalid_gzip_is_a_typed_error() -> None:
    good = gzip.compress((HEADER + "2026-09-01,1,USD,/r1,m1\n").encode())
    for bad in (good[:-6], b"not gzip at all"):
        src = FakeSource(_manifest([PART], compression="Gzip"), {PART: bad})
        with pytest.raises(InvalidSchemaError):
            await read_export(src, basis="actual")


@pytest.mark.parametrize(
    "cell",
    # underscore forms, Arabic-Indic digits, fullwidth digits, malformed exponent, NaN
    ["1_0", "1_000.5", chr(0x663) + "." + chr(0x665), chr(0xFF11) + chr(0xFF12), "1e", "NaN"],
)
def test_underscore_and_non_ascii_digits_are_unknown_not_numbers(cell: str) -> None:
    (row,) = parse_cost_csv(HEADER + f"2026-09-01,{cell},USD,/r1,m1\n", basis="actual")
    assert row.cost is None


@pytest.mark.parametrize(
    ("cell", "expected"),
    [("1.50", "1.50"), ("-2", "-2"), (".5", "0.5"), ("1E+2", "1E+2")],
)
def test_plain_ascii_numbers_still_parse(cell: str, expected: str) -> None:
    (row,) = parse_cost_csv(HEADER + f"2026-09-01,{cell},USD,/r1,m1\n", basis="actual")
    assert row.cost == Decimal(expected)


async def test_missing_partition_is_detected_not_equal_by_construction() -> None:
    text = HEADER + "2026-09-01,1,USD,/r1,m1\n"
    src = FakeSource(
        _manifest([PART, "folder/run/part1.csv"]), {PART: text.encode()}
    )  # part1 absent
    result = await read_export(src, basis="actual")
    assert result.blobs_expected == 2
    assert result.blobs_read == 1
    assert result.blobs_missing == ("folder/run/part1.csv",)
    assert result.complete is False


async def test_manifest_listing_fewer_blobs_than_blobcount_is_incomplete() -> None:
    manifest = _manifest([PART])
    manifest["blobCount"] = 3
    src = FakeSource(manifest, {PART: (HEADER + "2026-09-01,1,USD,/r1,m1\n").encode()})
    result = await read_export(src, basis="actual")
    assert (result.blobs_read, result.blobs_expected) == (1, 3)
    assert result.complete is False


async def test_dateless_rows_are_surfaced_in_read_result_and_variance_report() -> None:
    text = HEADER + "2026-09-01,1,USD,/r1,m1\n,5,USD,/r1,m1\nnot-a-date,7,USD,/r1,m1\n"
    src = FakeSource(_manifest([PART]), {PART: text.encode()})
    connector = AzureBillingConnector(source=src, basis="actual")
    result = await connector.read()
    assert result.rows_dropped_no_date == 2
    assert result.export.rows_without_date == 2
    assert len(result.aggregates) == 1
    report = build_variance_report(
        result.aggregates, [], rows_without_date=result.rows_dropped_no_date
    )
    assert report.billing_rows_without_date == 2
    assert build_variance_report(result.aggregates, []).billing_rows_without_date == 0


def test_aggregate_import_is_usable() -> None:
    agg = BillingAggregate(
        usage_date=date(2026, 9, 1),
        resource_id=None,
        meter_id=None,
        currency="USD",
        basis="actual",
        amount_kind="estimated",
        cost=None,
        row_count=1,
        null_cost_rows=1,
    )
    assert agg.cost is None
