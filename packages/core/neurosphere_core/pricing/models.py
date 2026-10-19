"""Immutable, content-hashed price snapshots (PRP-15 item 3).

A ``PriceSnapshot`` is a frozen copy of a machine-readable price source at one retrieval date:
Azure Retail Prices API data (``azure_retail_prices``) or an official provider price sheet
(``provider_price_sheet``). Its ``content_hash`` is the sha256 of a canonical JSON serialization
of everything except the hash itself, and it is verified on construction, so a snapshot cannot be
altered after the fact without its hash (and therefore its identity) changing.

Cloud applicability is explicit. The Retail Prices API covers the Commercial cloud only, so a
``azure_retail_prices`` snapshot may apply to ``commercial`` and never to ``government``; a
Government projection needs a provider sheet that says so. Commercial prices are never a
fallback for Government.

Money is ``Decimal``; floats are rejected. Token rows are normalised to a price per 1M tokens
when a snapshot is mapped into the ledger ``PriceVersion`` (the ledger is read, never edited).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Final, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from neurosphere_core.ledger.models import Currency
from neurosphere_core.ledger.prices import ModelRate, PriceVersion, Rate

Cloud = Literal["commercial", "government"]
SnapshotSource = Literal["azure_retail_prices", "provider_price_sheet"]
TokenKind = Literal["input", "output", "cached"]

RETAIL_PRICES_HOST: Final = "prices.azure.com"
SNAPSHOT_ID_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
# Units of measure that denote a block of tokens, and how many tokens that block is.
_TOKEN_UNITS: Final = {"1K": Decimal(1_000), "1M": Decimal(1_000_000)}
_PER_MILLION: Final = Decimal(1_000_000)


def _no_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("money must be a Decimal or a decimal string, never a float")
    return value


Price = Annotated[Decimal, BeforeValidator(_no_float), Field(ge=0, allow_inf_nan=False)]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TokenMeter(_Frozen):
    """Maps a price row to a model token price (the Retail Prices API has no model fields)."""

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    model_version: str | None = None
    kind: TokenKind


class PriceRow(_Frozen):
    """One price. Field names follow the Retail Prices API ``Items[]`` shape, in snake_case."""

    service_name: str = Field(min_length=1)
    sku_name: str = Field(min_length=1)
    meter_id: str | None = None
    meter_name: str | None = None
    arm_region_name: str | None = None
    unit_of_measure: str = Field(min_length=1)
    retail_price: Price
    unit_price: Price | None = None
    price_type: str = "Consumption"
    effective_start_date: date | None = None
    token_meter: TokenMeter | None = None

    @model_validator(mode="after")
    def _token_unit(self) -> Self:
        if self.token_meter is not None and self.unit_of_measure not in _TOKEN_UNITS:
            raise ValueError(f"token row unit_of_measure must be one of {sorted(_TOKEN_UNITS)}")
        return self

    def price_per_million_tokens(self) -> Decimal | None:
        """``retail_price`` normalised to 1M tokens, or None for a non-token row."""
        if self.token_meter is None:
            return None
        return self.retail_price * _PER_MILLION / _TOKEN_UNITS[self.unit_of_measure]


def _fmt_decimal(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text


def _canonical_row(row: PriceRow) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in PriceRow.model_fields:
        value = getattr(row, name)
        if isinstance(value, Decimal):
            out[name] = _fmt_decimal(value)
        elif isinstance(value, date):
            out[name] = value.isoformat()
        elif isinstance(value, TokenMeter):
            out[name] = value.model_dump(mode="json")
        else:
            out[name] = value
    return out


class PriceSnapshot(_Frozen):
    snapshot_id: str
    source: SnapshotSource
    source_url: str = Field(min_length=1)
    retrieval_date: date
    effective_date: date
    currency: Currency
    clouds: tuple[Cloud, ...] = Field(min_length=1)
    synthetic: bool = False
    notes: str = ""
    rows: tuple[PriceRow, ...]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("snapshot_id")
    @classmethod
    def _id_shape(cls, value: str) -> str:
        if not SNAPSHOT_ID_PATTERN.match(value):
            raise ValueError("snapshot_id must match ^[a-z0-9][a-z0-9._-]{0,63}$")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if len(set(self.clouds)) != len(self.clouds):
            raise ValueError("duplicate cloud")
        if self.source == "azure_retail_prices":
            # Learn: the Retail Prices API supports prices on Commercial Cloud only.
            if self.clouds != ("commercial",):
                raise ValueError("azure_retail_prices snapshots apply to commercial only")
            if urlsplit(self.source_url).hostname != RETAIL_PRICES_HOST:
                raise ValueError(
                    f"azure_retail_prices source_url host must be {RETAIL_PRICES_HOST}"
                )
        keys: set[tuple[str, str, str | None, str]] = set()
        for row in self.rows:
            meter = row.token_meter
            if meter is not None:
                key = (meter.provider, meter.model, meter.model_version, meter.kind)
                if key in keys:
                    raise ValueError(f"duplicate token price row {key}")
                keys.add(key)
        if self.content_hash != compute_content_hash(self):
            raise ValueError("content_hash does not match the snapshot content")
        return self

    def applies_to(self, cloud: str) -> bool:
        return cloud in self.clouds

    def to_price_version(self) -> PriceVersion:
        """Map the token rows into a ledger ``PriceVersion`` (id = ``snapshot_id``).

        A model needs both an input and an output price to get a rate; a model with only one is
        left out (an unresolved price, never a zero).
        """
        grouped: dict[tuple[str, str, str | None], dict[str, Decimal]] = {}
        for row in self.rows:
            meter = row.token_meter
            per_million = row.price_per_million_tokens()
            if meter is None or per_million is None:
                continue
            key = (meter.provider, meter.model, meter.model_version)
            grouped.setdefault(key, {})[meter.kind] = per_million
        rates = [
            ModelRate(
                provider=provider,
                model=model,
                model_version=version,
                rate=Rate(
                    input=prices["input"], output=prices["output"], cached=prices.get("cached")
                ),
            )
            for (provider, model, version), prices in sorted(
                grouped.items(), key=lambda item: (item[0][0], item[0][1], item[0][2] or "")
            )
            if "input" in prices and "output" in prices
        ]
        return PriceVersion(
            price_version_id=self.snapshot_id,
            effective_date=self.effective_date,
            currency=self.currency,
            source=f"{self.source}:{self.source_url}",
            rates=rates,
        )


def _canonical_payload(snapshot: PriceSnapshot) -> dict[str, Any]:
    rows = sorted(
        (_canonical_row(row) for row in snapshot.rows),
        key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
    )
    return {
        "snapshot_id": snapshot.snapshot_id,
        "source": snapshot.source,
        "source_url": snapshot.source_url,
        "retrieval_date": snapshot.retrieval_date.isoformat(),
        "effective_date": snapshot.effective_date.isoformat(),
        "currency": snapshot.currency,
        "clouds": sorted(snapshot.clouds),
        "synthetic": snapshot.synthetic,
        "notes": snapshot.notes,
        "rows": rows,
    }


def canonical_json(snapshot: PriceSnapshot) -> str:
    """Canonical serialization the hash is computed over: sorted keys, no whitespace, sorted
    clouds and rows (so row order never changes identity), decimals as normalised plain strings."""
    return json.dumps(
        _canonical_payload(snapshot), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def compute_content_hash(snapshot: PriceSnapshot) -> str:
    return hashlib.sha256(canonical_json(snapshot).encode("utf-8")).hexdigest()


def build_snapshot(
    *,
    snapshot_id: str,
    source: SnapshotSource,
    source_url: str,
    retrieval_date: date,
    effective_date: date,
    currency: str,
    clouds: tuple[Cloud, ...],
    rows: list[PriceRow] | tuple[PriceRow, ...],
    synthetic: bool = False,
    notes: str = "",
) -> PriceSnapshot:
    """Create a snapshot and stamp its content hash."""
    fields: dict[str, Any] = {
        "snapshot_id": snapshot_id,
        "source": source,
        "source_url": source_url,
        "retrieval_date": retrieval_date,
        "effective_date": effective_date,
        "currency": currency,
        "clouds": clouds,
        "synthetic": synthetic,
        "notes": notes,
        "rows": tuple(rows),
    }
    model_construct = PriceSnapshot.model_construct(content_hash="0" * 64, **fields)
    digest = compute_content_hash(model_construct)
    return PriceSnapshot(content_hash=digest, **fields)
