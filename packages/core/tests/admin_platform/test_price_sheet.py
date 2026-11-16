"""PRP-44 item 1: price sheet conversion, coverage and append-only upload."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from neurosphere_contracts.admin.v1.price_sheet_upload import PriceSheetUpload
from neurosphere_core.admin.platform import (
    PriceSheetAdmin,
    coverage_report,
    price_sheet_to_snapshot,
)
from neurosphere_core.errors import InvalidSchemaError, StaleVersionError
from neurosphere_core.pricing import InMemoryPriceSnapshotStore, compute_content_hash

from .platform_helpers import sheet_body, token_row


def _upload(**over: Any) -> PriceSheetUpload:
    return PriceSheetUpload.model_validate(sheet_body(**over))


def test_upload_round_trips_to_a_snapshot_with_a_matching_hash() -> None:
    snapshot = price_sheet_to_snapshot(_upload())
    assert snapshot.content_hash == compute_content_hash(snapshot)
    assert snapshot.snapshot_id == "aoai-2026-11" and snapshot.effective_date == date(2026, 11, 1)
    version = snapshot.to_price_version()
    assert version.price_version_id == "aoai-2026-11"
    assert [r.model for r in version.rates] == ["gpt-4.1"]


def test_coverage_names_incomplete_models_and_unmetered_rows() -> None:
    report = coverage_report(price_sheet_to_snapshot(_upload()))
    assert report.models_priced == 1
    assert [(m.model, m.missing) for m in report.models_incomplete] == [("gpt-mini", ("output",))]
    assert report.rows_without_token_meter == 1 and report.rows == 4
    assert report.warnings == ("models_incomplete",)


def test_a_1k_row_is_normalised_to_one_million() -> None:
    rows = [token_row("m", "input", "0.002", "1K"), token_row("m", "output", "0.008", "1K")]
    version = price_sheet_to_snapshot(_upload(rows=rows)).to_price_version()
    assert version.rates[0].rate.input == Decimal("2")


async def test_upload_is_idempotent_on_equal_hash_and_conflicts_otherwise() -> None:
    store = InMemoryPriceSnapshotStore()
    admin = PriceSheetAdmin(store, cloud="commercial")
    first = await admin.upload(_upload())
    again = await admin.upload(_upload())
    assert first.created and not again.created
    assert first.snapshot.content_hash == again.snapshot.content_hash
    changed = _upload(
        rows=[token_row("gpt-4.1", "input", "3.00"), token_row("gpt-4.1", "output", "8")]
    )
    with pytest.raises(StaleVersionError) as caught:
        await admin.upload(changed)
    assert caught.value.reason == "snapshot_conflict"
    assert len(await admin.list()) == 1


async def test_sheet_for_another_cloud_is_refused() -> None:
    admin = PriceSheetAdmin(InMemoryPriceSnapshotStore(), cloud="government")
    with pytest.raises(InvalidSchemaError) as caught:
        await admin.upload(_upload())
    assert caught.value.reason == "cross_cloud"


async def test_synthetic_is_refused_unless_allowed() -> None:
    store = InMemoryPriceSnapshotStore()
    with pytest.raises(InvalidSchemaError) as caught:
        await PriceSheetAdmin(store, cloud="commercial").upload(_upload(synthetic=True))
    assert caught.value.reason == "synthetic_refused"
    local = PriceSheetAdmin(store, cloud="commercial", allow_synthetic=True)
    assert (await local.upload(_upload(synthetic=True))).created


def test_retail_prices_for_government_is_refused_by_the_model_rule() -> None:
    upload = _upload(
        source="azure_retail_prices",
        source_url="https://prices.azure.com/api/retail/prices",
        clouds=["government"],
    )
    with pytest.raises(InvalidSchemaError):
        price_sheet_to_snapshot(upload)


async def test_get_hides_a_snapshot_of_another_cloud() -> None:
    store = InMemoryPriceSnapshotStore()
    await PriceSheetAdmin(store, cloud="commercial").upload(_upload())
    assert await PriceSheetAdmin(store, cloud="government").get("aoai-2026-11") is None
    assert await PriceSheetAdmin(store, cloud="commercial").get("aoai-2026-11") is not None
