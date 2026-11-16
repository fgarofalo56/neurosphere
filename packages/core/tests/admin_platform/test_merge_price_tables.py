"""PRP-44 item 1: merging stored snapshots with a file price table."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from neurosphere_contracts.admin.v1.price_sheet_upload import PriceSheetUpload
from neurosphere_core.admin.platform import (
    PriceVersionConflictError,
    merge_price_tables,
    price_sheet_to_snapshot,
)
from neurosphere_core.ledger.prices import ModelRate, PriceTable, PriceVersion, Rate

from .platform_helpers import sheet_body, token_row


def _snapshot(**over: object):
    return price_sheet_to_snapshot(PriceSheetUpload.model_validate(sheet_body(**over)))  # type: ignore[arg-type]


def _file_version(version_id: str, input_price: str = "2.00") -> PriceVersion:
    return PriceVersion(
        price_version_id=version_id,
        effective_date=date(2026, 11, 1),
        currency="USD",
        source="provider_price_sheet:https://example.test/prices",
        rates=[
            ModelRate(
                provider="azure_openai",
                model="gpt-4.1",
                rate=Rate(input=Decimal(input_price), output=Decimal("8.00")),
            )
        ],
    )


def test_snapshot_version_is_resolvable_in_the_merged_table() -> None:
    table = merge_price_tables([_snapshot()], None, cloud="commercial")
    resolved = table.resolve("azure_openai", "gpt-4.1", None, date(2026, 11, 2))
    assert resolved is not None and resolved.version.price_version_id == "aoai-2026-11"


def test_file_and_snapshot_versions_union() -> None:
    table = merge_price_tables(
        [_snapshot()], PriceTable([_file_version("file-1")]), cloud="commercial"
    )
    assert {v.price_version_id for v in table.versions} == {"file-1", "aoai-2026-11"}


def test_equal_id_with_identical_content_collapses() -> None:
    snapshot = _snapshot()
    table = merge_price_tables(
        [snapshot], PriceTable([snapshot.to_price_version()]), cloud="commercial"
    )
    assert len(table.versions) == 1


def test_equal_id_with_different_content_refuses() -> None:
    other = PriceTable([_file_version("aoai-2026-11", "9.99")])
    with pytest.raises(PriceVersionConflictError) as caught:
        merge_price_tables([_snapshot()], other, cloud="commercial")
    assert caught.value.reason == "price_version_conflict"
    assert "9.99" not in str(caught.value)


def test_snapshot_of_another_cloud_is_skipped() -> None:
    table = merge_price_tables([_snapshot()], None, cloud="government")
    assert table.versions == []


def test_incomplete_models_are_left_out_not_zero() -> None:
    snapshot = _snapshot(rows=[token_row("only-in", "input", "1")])
    table = merge_price_tables([snapshot], None, cloud="commercial")
    assert table.resolve("azure_openai", "only-in", None, date(2026, 11, 2)) is None
