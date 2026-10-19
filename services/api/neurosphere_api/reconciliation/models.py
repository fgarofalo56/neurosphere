"""Wire models for the reconciliation view (PRP-14 item 4). See ``__init__`` for the contract."""

from __future__ import annotations

from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict

__all__ = [
    "DISCLAIMER",
    "REFERENCE_LABEL",
    "Freshness",
    "MetricValue",
    "ReconciliationResponse",
    "Reference",
    "ReferenceLine",
    "SourceLine",
    "UnknownRemainder",
    "Window",
]

DISCLAIMER: Final = "not_all_spend_observable"
REFERENCE_LABEL: Final = "ledger (one record per request)"


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MetricValue(_Wire):
    """``status: "unknown"`` always pairs with ``value: None``; never 0 for unknown."""

    value: float | None
    status: Literal["known", "unknown"]
    complete: bool
    price_version: None = None

    @classmethod
    def of(cls, value: float | None, *, complete: bool) -> Self:
        if value is None:
            return cls(value=None, status="unknown", complete=complete)
        return cls(value=value, status="known", complete=complete)


class Window(_Wire):
    start: str
    end: str


class Freshness(_Wire):
    watermark: str | None
    lag_seconds: float | None
    billing_source_freshness: str | None


class Reference(_Wire):
    label: str
    amount: MetricValue
    currency: str | None


class SourceLine(_Wire):
    source: Literal["gateway", "app", "billing"]
    granularity: Literal["request", "vendor", "unknown"]
    amount: MetricValue
    coverage: MetricValue
    variance: MetricValue
    currency: str | None


class UnknownRemainder(MetricValue):
    """A count of ledger entries whose amount is unknown (their money value is unknowable)."""

    unit: Literal["entries"] = "entries"


class ReferenceLine(Reference):
    entry_count: int
    unknown_entry_count: int


class ReconciliationResponse(_Wire):
    domain_id: str
    window: Window
    freshness: Freshness
    complete: bool
    truncated: bool
    reference: Reference
    references: list[ReferenceLine]
    sources: list[SourceLine]
    unknown_remainder: UnknownRemainder
    disclaimer: Literal["not_all_spend_observable"] = DISCLAIMER
