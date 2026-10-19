"""Hot-aggregate documents and the per-source contributions they are rebuilt from (PRP-14 item 1).

Two kinds of stored documents, both frozen with ``extra="forbid"``:

* ``Contribution``: the facts ONE outbox subject (a telemetry event, a ledger entry or an
  allocation record) adds to the aggregates. Keyed by a deterministic id, so a replay or a changed
  ledger entry REPLACES the previous contribution instead of adding to it. This is what makes the
  projection idempotent without cross-item transactions (the Cosmos emulator has none).
* ``AggregateDoc`` (one model per metric, discriminated on ``metric``): a bucket (customer, domain,
  grain, bucket start) of a rollup computed from ALL contributions of that bucket.

Null semantics (NS-01): ``None`` is unknown and is never 0. A total over partially unknown inputs
keeps the sum of the known parts and carries ``complete: False``; a total over only unknown inputs
is ``None``. Money is ``Decimal`` (the ledger ``Money`` type), never float.

Aggregate documents carry no wall-clock field: rebuilding from the same contributions yields an
equal document. Lag is computed at read time from ``watermark`` (see ``AggregateStatus``).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from neurosphere_core.ledger.models import UNKNOWN_CURRENCY, Money

SCHEMA_VERSION: Final = "1"
WINDOW_DAYS: Final = 90
"""Rolling window: contributions older than this fall out of the aggregates."""
HOUR_RETENTION_DAYS: Final = 14
"""The hour grain is materialized (and queryable) for this many days only."""
UNASSIGNED_DOMAIN: Final = "_unassigned"
"""Domain key for subjects that carry no ``domain_id``; they stay visible, never dropped."""
TIME_FORMAT: Final = "%Y-%m-%dT%H:%M:%SZ"
FINE_TIME_FORMAT: Final = "%Y-%m-%dT%H:%M:%S.%fZ"  # the ledger's fixed-width format

Metric = Literal["cost", "latency", "errors", "coverage", "reconciliation"]
Grain = Literal["day", "hour"]
CostKind = Literal["estimated", "invoiced"]
SourceName = Literal["gateway", "app", "billing"]
Granularity = Literal["request", "vendor", "unknown"]
Outcome = Literal["success", "error", "cancelled", "timeout", "unknown"]

SOURCES: Final[tuple[SourceName, ...]] = ("gateway", "app", "billing")

__all__ = [
    "FINE_TIME_FORMAT",
    "HOUR_RETENTION_DAYS",
    "SCHEMA_VERSION",
    "SOURCES",
    "TIME_FORMAT",
    "UNASSIGNED_DOMAIN",
    "UNKNOWN_CURRENCY",
    "WINDOW_DAYS",
    "AggregateDoc",
    "AggregateSeries",
    "AggregateStatus",
    "AggregateWindow",
    "AllocationFact",
    "Contribution",
    "CostFact",
    "CostPoint",
    "CoveragePoint",
    "EntryFact",
    "ErrorPoint",
    "EventFact",
    "LatencyPoint",
    "PriceVersionRef",
    "QueryResult",
    "ReconciliationPoint",
    "SourceFact",
    "SourceRollup",
    "aggregate_doc_id",
    "bucket_start",
    "format_bucket",
    "format_fine",
    "parse_time",
]


# --------------------------------------------------------------------------- time helpers


def parse_time(value: str) -> datetime:
    """Parse either fixed-width format (second or microsecond resolution) to aware UTC."""
    for fmt in (FINE_TIME_FORMAT, TIME_FORMAT):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    raise ValueError("unrecognized timestamp format")


def format_fine(value: datetime) -> str:
    return value.astimezone(UTC).strftime(FINE_TIME_FORMAT)


def format_bucket(value: datetime) -> str:
    return value.astimezone(UTC).strftime(TIME_FORMAT)


def bucket_start(moment: datetime, grain: Grain) -> datetime:
    """Start of the UTC day or hour containing ``moment``."""
    utc = moment.astimezone(UTC)
    if grain == "day":
        return utc.replace(hour=0, minute=0, second=0, microsecond=0)
    return utc.replace(minute=0, second=0, microsecond=0)


def aggregate_doc_id(
    customer_id: str, domain_id: str, metric: str, grain: str, start: str, series_key: str
) -> str:
    """Deterministic id: the same bucket and series always map to the same document."""
    raw = "|".join(("aggregate", customer_id, domain_id, metric, grain, start, series_key))
    return "agg-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------- contributions


class EventFact(_Frozen):
    """A ``model_call`` span: latency and outcome. ``None`` duration is unknown, never 0."""

    duration_ms: int | None = Field(default=None, ge=0)
    outcome: Outcome = "unknown"


class CostFact(_Frozen):
    """One estimated or invoiced cost component of a ledger entry."""

    kind: CostKind
    currency: str | None = None  # None: not determinable (lands in the XXX bucket)
    amount: Money | None = None  # None: unknown
    price_version_ids: list[str] = Field(default_factory=list)


class SourceFact(_Frozen):
    """What one observation source (gateway, app, billing) reported for one ledger entry."""

    source: SourceName
    amount: Money | None = None  # None: unknown (or not in the entry's currency bucket)
    known: bool = False


class EntryFact(_Frozen):
    """A ledger entry's reference amount, coverage inputs and per-source reports."""

    currency: str  # coverage/reconciliation bucket: totals.py semantics, XXX when undeterminable
    amount: Money | None = None  # authoritative amount (the reference counts the request once)
    price_unresolved: bool = False
    sources: list[SourceFact] = Field(default_factory=list)

    @property
    def amount_known(self) -> bool:
        return self.amount is not None


class AllocationFact(_Frozen):
    """Request-less spend (vendor/period billing or unattributed). Reconciliation only."""

    source: SourceName
    granularity: Granularity
    currency: str
    amount: Money | None = None


class Contribution(_Frozen):
    doc_type: Literal["contribution"] = "contribution"
    schema_version: str = SCHEMA_VERSION
    id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    domain_id: str = Field(min_length=1)
    origin: Literal["event", "ledger_entry", "allocation"]
    occurred_at: str  # bucketing time, fixed-width UTC
    observed_at: str  # freshness time, fixed-width UTC
    billing_observed_at: str | None = None
    event: EventFact | None = None
    costs: list[CostFact] = Field(default_factory=list)
    entry: EntryFact | None = None
    allocation: AllocationFact | None = None

    @property
    def occurred(self) -> datetime:
        return parse_time(self.occurred_at)


# --------------------------------------------------------------------------- aggregate docs


class PriceVersionRef(_Frozen):
    id: str
    effective_date: date | None = None  # None when the price table cannot resolve the id


class _AggregateBase(_Frozen):
    doc_type: Literal["aggregate"] = "aggregate"
    schema_version: str = SCHEMA_VERSION
    id: str
    customer_id: str
    domain_id: str
    grain: Grain
    bucket_start: str  # fixed-width UTC, ``TIME_FORMAT``
    series_key: str
    watermark: str | None = None  # latest ``observed_at`` of the contributions in this document
    complete: bool  # False when any input was unknown or only partly known


class CostPoint(_AggregateBase):
    """Estimated and invoiced are SEPARATE series (``estimated:USD``, ``invoiced:USD``)."""

    metric: Literal["cost"] = "cost"
    kind: CostKind
    currency: str
    amount: Money | None  # sum of the KNOWN entries; None when none is known
    entry_count: int
    known_count: int
    price_versions: list[PriceVersionRef] = Field(default_factory=list)


class LatencyPoint(_AggregateBase):
    metric: Literal["latency"] = "latency"
    sample_count: int
    missing_count: int  # spans without a duration: unknown, excluded from the percentiles
    p50_ms: int | None = None
    p95_ms: int | None = None
    p99_ms: int | None = None


class ErrorPoint(_AggregateBase):
    metric: Literal["errors"] = "errors"
    request_count: int  # spans with a known outcome
    unknown_count: int  # spans whose outcome is unknown
    error_count: int | None = None  # known errors/timeouts; None when no outcome is known
    error_rate: float | None = None  # error_count / request_count; None when unknowable


class CoveragePoint(_AggregateBase):
    """Same semantics as ``neurosphere_core.ledger.totals.compute_totals`` per currency."""

    metric: Literal["coverage"] = "coverage"
    currency: str
    entry_count: int
    known_count: int
    unresolved_count: int
    unknown_count: int
    coverage: float | None = None
    amount: Money | None = None  # the authoritative total of the known entries


class SourceRollup(_Frozen):
    source: SourceName
    granularity: Granularity
    observed_entry_count: int  # ledger entries this source reported on (known or not)
    known_count: int  # of those, entries with a known amount from this source
    allocation_count: int  # request-less records from this source
    amount: Money | None = None  # sum of the known parts; None when none is known
    coverage: float | None = None  # known_count / reference entries; None = unknown, not 0
    complete: bool = False


class ReconciliationPoint(_AggregateBase):
    metric: Literal["reconciliation"] = "reconciliation"
    currency: str
    reference_amount: Money | None = None  # ledger authoritative sum, each request once
    reference_entry_count: int = 0
    reference_known_count: int = 0
    sources: list[SourceRollup]  # always gateway, app, billing in that order


AggregateDoc = Annotated[
    CostPoint | LatencyPoint | ErrorPoint | CoveragePoint | ReconciliationPoint,
    Field(discriminator="metric"),
]
AGGREGATE_ADAPTER: Final[TypeAdapter[AggregateDoc]] = TypeAdapter(AggregateDoc)


# --------------------------------------------------------------------------- status and query


class AggregateStatus(_Frozen):
    """Per-customer freshness: how far the projection has applied. Monotonic, replay-safe."""

    doc_type: Literal["status"] = "status"
    id: str = "status"
    customer_id: str
    watermark: str | None = None  # max ``observed_at`` applied (event time, not wall clock)
    billing_observed_at: str | None = None  # max billing ``observed_at`` (source freshness)

    def lag_seconds(self, now: datetime) -> float | None:
        """Seconds between ``now`` and the watermark; ``None`` when nothing was applied."""
        if self.watermark is None:
            return None
        return max(0.0, (now - parse_time(self.watermark)).total_seconds())


@dataclass(frozen=True, slots=True)
class AggregateWindow:
    """Half-open ``[start, end)`` over ``bucket_start``."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("window bounds must be timezone-aware")
        if self.end < self.start:
            raise ValueError("window end precedes start")

    @property
    def span(self) -> timedelta:
        return self.end - self.start


class AggregateSeries(_Frozen):
    key: str
    points: tuple[AggregateDoc, ...]  # oldest first, at most ``max_points``


class QueryResult(_Frozen):
    series: tuple[AggregateSeries, ...]  # sorted by key, at most ``max_series``
    truncated: bool  # series or points were cut by the caller's bounds
