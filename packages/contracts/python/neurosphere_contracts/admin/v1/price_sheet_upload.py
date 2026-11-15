# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictBool, StrictStr

from . import common


class ArmRegionName(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[a-z][a-z0-9]{1,31}$")]


class Label(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=256, min_length=1)]


class PriceSheetTokenMeter(BaseModel):
    """
    Maps a price row to a model token price (core TokenMeter).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    provider: Label
    model: Label
    model_version: Label | None = None
    kind: Literal["input", "output", "cached"]


class PriceSheetRow(BaseModel):
    """
    One price (core PriceRow; Retail Prices API Items[] field names in snake_case).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    service_name: Label
    sku_name: Label
    meter_id: Label | None = None
    meter_name: Label | None = None
    arm_region_name: ArmRegionName | None = None
    unit_of_measure: Label
    retail_price: common.DecimalAmount
    unit_price: common.DecimalAmount | None = None
    price_type: Label | None = None
    effective_start_date: common.Date | None = None
    token_meter: PriceSheetTokenMeter | None = None


class PriceSheetUpload(BaseModel):
    """
    An operator-uploaded price sheet (PRP-44). Maps one to one onto core pricing PriceSnapshot minus content_hash: the server builds the snapshot with build_snapshot, which stamps the hash, so an upload can never assert its own hash. Money is a decimal string, never a float. azure_retail_prices sheets apply to commercial only and their source_url host is prices.azure.com; Commercial prices are never a fallback for Government (both enforced again by PriceSnapshot). Rules JSON Schema cannot express are checked by tests/contracts/validators.py::check_price_sheet_upload: token price rows are unique per (provider, model, model_version, kind) and a token row's unit_of_measure is 1K or 1M.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    snapshot_id: common.Slug
    source: Literal["azure_retail_prices", "provider_price_sheet"]
    source_url: common.HttpsUrl
    """
    Where the sheet was obtained. HTTPS, no query string or fragment.
    """
    retrieval_date: common.Date
    effective_date: common.Date
    currency: common.Currency
    clouds: Annotated[list[common.Cloud], Field(max_length=2, min_length=1)]
    synthetic: StrictBool
    """
    true for demo or test sheets; synthetic prices are labelled wherever they are shown.
    """
    notes: Annotated[StrictStr, Field(max_length=2000)]
    rows: Annotated[list[PriceSheetRow], Field(max_length=10000, min_length=1)]
