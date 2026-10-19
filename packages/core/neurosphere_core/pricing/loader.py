"""Load committed price snapshot files (no network).

Two file shapes, both with a ``metadata`` object (snapshot id, source, source_url, retrieval_date,
effective_date, currency, clouds, synthetic, notes):

* Retail Prices API data: ``Items`` in the API's camelCase ``Items[]`` shape plus ``token_meters``
  (meterId -> provider/model/version/kind), because API rows carry no model fields.
* Provider price sheet: ``rows`` in ``PriceRow`` shape.

Decimals are parsed from JSON with ``Decimal`` so no float ever carries money.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from neurosphere_core.pricing.models import PriceRow, PriceSnapshot, TokenMeter, build_snapshot

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _date(value: str) -> date:
    return date.fromisoformat(value[:10])


def retail_item_to_row(item: dict[str, Any], token_meters: dict[str, Any]) -> PriceRow:
    """Map one Retail Prices API ``Items[]`` entry to a ``PriceRow``."""
    meter_id = item.get("meterId")
    meter = token_meters.get(meter_id) if meter_id is not None else None
    start = item.get("effectiveStartDate")
    return PriceRow(
        service_name=item["serviceName"],
        sku_name=item["skuName"],
        meter_id=meter_id,
        meter_name=item.get("meterName"),
        arm_region_name=item.get("armRegionName"),
        unit_of_measure=item["unitOfMeasure"],
        retail_price=item["retailPrice"],
        unit_price=item.get("unitPrice"),
        price_type=item.get("type", "Consumption"),
        effective_start_date=_date(start) if start else None,
        token_meter=TokenMeter(**meter) if meter is not None else None,
    )


def snapshot_from_document(document: dict[str, Any]) -> PriceSnapshot:
    meta = document["metadata"]
    if "Items" in document:
        meters = document.get("token_meters", {})
        rows = [retail_item_to_row(item, meters) for item in document["Items"]]
    else:
        rows = [PriceRow.model_validate(row) for row in document["rows"]]
    return build_snapshot(
        snapshot_id=meta["snapshot_id"],
        source=meta["source"],
        source_url=meta["source_url"],
        retrieval_date=_date(meta["retrieval_date"]),
        effective_date=_date(meta["effective_date"]),
        currency=meta["currency"],
        clouds=tuple(meta["clouds"]),
        rows=rows,
        synthetic=bool(meta.get("synthetic", False)),
        notes=meta.get("notes", ""),
    )


def load_snapshot_file(path: Path) -> PriceSnapshot:
    document = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    return snapshot_from_document(document)
