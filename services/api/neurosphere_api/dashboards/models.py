"""Response models for the dashboards wire contract (PRP-14 "Wire contract").

``MetricValue`` carries the null semantics: ``status: "unknown"`` always pairs with
``value: null`` and a known value (including a genuine 0) pairs with ``status: "known"``. Unknown
is never rendered as 0. A total built from partly unknown parts is the sum of the known parts with
``complete: false``.

No ``from __future__ import annotations``: FastAPI and pydantic resolve these annotations at
import time and the module has no forward references.
"""

from datetime import date
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

__all__ = [
    "UNKNOWN",
    "AnalyticsInfo",
    "DashboardResponse",
    "Freshness",
    "MetricValue",
    "Point",
    "PriceVersion",
    "Series",
    "Window",
    "known_value",
]

MetricName = Literal["cost", "latency", "errors", "coverage"]
GrainName = Literal["day", "hour"]
SeriesUnit = Literal["currency", "ms", "ratio", "count"]
SeriesKind = Literal["estimated", "invoiced"]
AnalyticsStateName = Literal["available", "delayed", "disabled"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PriceVersion(_Model):
    id: str
    effective_date: date


class MetricValue(_Model):
    value: float | None
    status: Literal["known", "unknown"]
    complete: bool
    price_version: PriceVersion | None = None

    @model_validator(mode="after")
    def _pair_status_and_value(self) -> Self:
        if (self.status == "unknown") != (self.value is None):
            raise ValueError("status unknown pairs with value null, and only with it")
        if self.status == "unknown" and self.complete:
            raise ValueError("an unknown value cannot be complete")
        return self


UNKNOWN = MetricValue(value=None, status="unknown", complete=False, price_version=None)


def known_value(
    value: float | int | Decimal, *, complete: bool, price_version: PriceVersion | None = None
) -> MetricValue:
    """A known value; ``0`` stays a known 0."""
    return MetricValue(
        value=float(value), status="known", complete=complete, price_version=price_version
    )


class Point(_Model):
    t: str
    value: MetricValue


class Series(_Model):
    key: str
    label: str
    kind: SeriesKind | None
    unit: SeriesUnit
    currency: str | None
    total: MetricValue
    points: list[Point]


class Window(_Model):
    start: str
    end: str


class Freshness(_Model):
    watermark: str | None
    lag_seconds: float | None
    billing_source_freshness: str | None


class AnalyticsInfo(_Model):
    state: AnalyticsStateName
    reason: str | None


class DashboardResponse(_Model):
    metric: MetricName
    domain_id: str
    grain: GrainName
    window: Window
    freshness: Freshness
    analytics: AnalyticsInfo
    complete: bool
    truncated: bool
    series: list[Series]
    price_versions: list[PriceVersion]
