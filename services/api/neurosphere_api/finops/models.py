"""Wire contract for the FinOps forecast (PRP-21 item 4).

Rules enforced by schema, not by convention:

* A forecast response MUST cite a price version (``price_version_id``, non-empty, and one of
  ``price_version_ids``). A response without one does not validate.
* ``estimated`` and ``invoiced`` are two separate, differently typed series (``kind`` is a
  ``Literal`` per class). There is no combined total anywhere, and an invoiced series cannot be
  placed in the estimated slot or the reverse.
* ``Amount`` carries the unknown-not-zero semantics: ``status: "unknown"`` pairs with
  ``value: null`` (and only with it), a known value (including a genuine 0) pairs with
  ``status: "known"``, and an unknown amount is never complete. A sum built from partly unknown
  parts is the sum of the known parts with ``complete: false``.
* Money is ``Decimal`` (12 fractional digits, serialized as a plain decimal string). Floats are
  rejected on input.

No ``from __future__ import annotations``: FastAPI and pydantic resolve these annotations at
import time.
"""

from datetime import date
from decimal import Decimal
from typing import Any, Literal, Self

from neurosphere_core.ledger.models import Money
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "Amount",
    "EstimatedSeries",
    "ForecastMethod",
    "ForecastResponse",
    "ForecastValue",
    "InvoicedSeries",
    "SeriesPoint",
    "SeriesSummary",
    "known_amount",
    "unknown_amount",
]

Phase = Literal["history", "horizon"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("money must be a Decimal or a decimal string, never a float")
    return value


class Amount(_Model):
    value: Money | None = None
    status: Literal["known", "unknown"]
    complete: bool
    reason: str | None = None  # why unknown / incomplete, machine readable

    @field_validator("value", mode="before")
    @classmethod
    def _no_float(cls, value: Any) -> Any:
        return _reject_float(value)

    @model_validator(mode="after")
    def _pair_status_and_value(self) -> Self:
        if (self.status == "unknown") != (self.value is None):
            raise ValueError("status unknown pairs with value null, and only with it")
        if self.status == "unknown" and self.complete:
            raise ValueError("an unknown amount cannot be complete")
        return self


def unknown_amount(reason: str) -> Amount:
    return Amount(value=None, status="unknown", complete=False, reason=reason)


def known_amount(value: Decimal, *, complete: bool, reason: str | None = None) -> Amount:
    return Amount(value=value, status="known", complete=complete, reason=reason)


class ForecastValue(_Model):
    """Point forecast with its uncertainty band (lower <= value <= upper, all >= 0)."""

    value: Money
    lower: Money
    upper: Money

    @field_validator("value", "lower", "upper", mode="before")
    @classmethod
    def _no_float(cls, value: Any) -> Any:
        return _reject_float(value)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not (Decimal(0) <= self.lower <= self.value <= self.upper):
            raise ValueError("band must satisfy 0 <= lower <= value <= upper")
        return self


class SeriesPoint(_Model):
    day: date
    phase: Phase
    actual: Amount
    forecast: ForecastValue | None = None
    within_band: bool | None = None  # only when both a forecast and a known actual exist

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.phase == "history" and self.forecast is not None:
            raise ValueError("history points carry no forecast")
        if self.within_band is not None and (
            self.forecast is None or self.actual.status != "known"
        ):
            raise ValueError("within_band needs a forecast and a known actual")
        return self


class SeriesSummary(_Model):
    """Totals over the series' own days. ``complete`` is false when any day is unknown or
    incomplete; the number is then the sum of the known parts, never a silent smaller figure."""

    history_actual: Amount
    horizon_actual: Amount
    horizon_forecast: ForecastValue | None = None  # sums of daily values/bounds (conservative)


class _SeriesBase(_Model):
    currency: str = Field(pattern="^[A-Z]{3}$")
    points: list[SeriesPoint]
    summary: SeriesSummary
    forecast_available: bool
    forecast_unavailable_reason: str | None = None
    fit_points: int = Field(ge=0)
    excluded_incomplete_days: int = Field(ge=0)
    residual_std: Money | None = None

    @model_validator(mode="after")
    def _availability(self) -> Self:
        horizon_has_forecast = any(
            p.forecast is not None for p in self.points if p.phase == "horizon"
        )
        if self.forecast_available != horizon_has_forecast:
            raise ValueError("forecast_available must match the presence of horizon forecasts")
        if not self.forecast_available and self.forecast_unavailable_reason is None:
            raise ValueError("an unavailable forecast states why")
        return self


class EstimatedSeries(_SeriesBase):
    kind: Literal["estimated"] = "estimated"


class InvoicedSeries(_SeriesBase):
    kind: Literal["invoiced"] = "invoiced"


class ForecastMethod(_Model):
    name: Literal["linear_trend_ols"] = "linear_trend_ols"
    description: str
    confidence_level: str  # decimal string, e.g. "0.95"
    z: str  # normal quantile used for the band, e.g. "1.96"
    min_fit_points: int
    history_days: int
    horizon_days: int
    savings_claim: Literal[False] = False


class ForecastResponse(_Model):
    domain_id: str
    as_of: date  # first forecast day; history is strictly before it
    method: ForecastMethod
    price_version_id: str = Field(min_length=1, max_length=128)
    price_version_ids: list[str] = Field(min_length=1)
    estimated: EstimatedSeries
    invoiced: InvoicedSeries

    @model_validator(mode="after")
    def _cites_version(self) -> Self:
        if self.price_version_id not in self.price_version_ids:
            raise ValueError("price_version_id must be one of price_version_ids")
        return self
