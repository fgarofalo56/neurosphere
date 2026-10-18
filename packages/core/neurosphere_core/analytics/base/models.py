"""Closed, typed request and result models for the analytics contracts (PRP-11, ADR-0007).

Nothing here accepts query text. Every request field is a closed enum, a bounded number, a
timestamp, or a short value matched against a fixed character pattern; values only ever reach
an engine as bound parameters. ``IdentityScope`` is deliberately NOT a request field: it is
server-derived and is a required keyword argument on every protocol method.

Unknown is null, never 0: a metric missing on a row aggregates as unknown. ``count`` counts
known values (a measured count, possibly 0); every cell also carries ``unknown_count``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from neurosphere_contracts.query.v1.budget import Budget
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

MAX_TIME_RANGE = timedelta(days=366)
MAX_GROUP_BY = 4
MAX_FILTERS = 8
MAX_FILTER_VALUES = 50
FILTER_VALUE_PATTERN = r"^[A-Za-z0-9._:/=@+-]{1,256}$"

Cloud = Literal["commercial", "government"]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Metric(StrEnum):
    EVENTS = "events"  # row count; only valid with the count aggregation
    COST_AMOUNT = "cost_amount"  # Decimal money; needs a currency filter or currency group
    INPUT_TOKENS = "input_tokens"
    OUTPUT_TOKENS = "output_tokens"
    DURATION_MS = "duration_ms"


INTEGER_METRICS = frozenset({Metric.INPUT_TOKENS, Metric.OUTPUT_TOKENS, Metric.DURATION_MS})


class Aggregation(StrEnum):
    COUNT = "count"
    SUM = "sum"
    MIN = "min"
    MAX = "max"
    APPROX_QUANTILE = "approx_quantile"


class Dimension(StrEnum):
    """Group-by and filter dimensions over normalized telemetry/cost fields."""

    DOMAIN_ID = "domain_id"
    PROVIDER = "provider"
    MODEL = "model"
    SPAN_KIND = "span_kind"
    OUTCOME = "outcome"
    CURRENCY = "currency"


class Granularity(StrEnum):
    HOUR = "hour"
    DAY = "day"


class FilterOp(StrEnum):
    EQ = "eq"
    IN = "in"
    IS_UNKNOWN = "is_unknown"


FilterValue = Annotated[StrictStr, Field(pattern=FILTER_VALUE_PATTERN)]


class FilterClause(_Closed):
    """One typed predicate. Clauses are ANDed; they can only narrow the scope, never widen it.

    ``eq`` and ``in`` never match unknown (null) values; ``is_unknown`` matches only them.
    """

    field: Dimension
    op: FilterOp
    values: Annotated[tuple[FilterValue, ...], Field(max_length=MAX_FILTER_VALUES)] = ()

    @model_validator(mode="after")
    def _arity(self) -> Self:
        if self.op is FilterOp.EQ and len(self.values) != 1:
            raise ValueError("op eq takes exactly one value")
        if self.op is FilterOp.IN and (
            not self.values or len(set(self.values)) != len(self.values)
        ):
            raise ValueError("op in takes one or more unique values")
        if self.op is FilterOp.IS_UNKNOWN and self.values:
            raise ValueError("op is_unknown takes no values")
        return self


class TimeRange(_Closed):
    """``start`` inclusive, ``end`` exclusive, UTC; at most 366 days."""

    start: AwareDatetime
    end: AwareDatetime

    @field_validator("start", "end")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if self.end - self.start > MAX_TIME_RANGE:
            raise ValueError("time range exceeds 366 days")
        return self


class AnalyticsBudget(_Closed):
    """Enforced per request. All fields are required; there are no defaults.

    ``query`` is the PRP-01 shared budget: ``timeout_ms`` (wall clock) and ``limit`` (maximum
    rows RETURNED); ``max_depth`` is 0 for analytics. ``max_rows_scanned`` and
    ``max_cost_units`` bound the work the engine may do. Exceeding the timeout, rows scanned,
    cost units or the returned-row limit cancels the work and raises ``rate_limited``.
    """

    query: Budget
    max_rows_scanned: Annotated[StrictInt, Field(ge=1, le=10_000_000_000)]
    max_cost_units: Annotated[Decimal, Field(gt=0, max_digits=24, decimal_places=6)]


class AggregateRequest(_Closed):
    """A bounded aggregation. ``budget`` and ``time_range`` are required."""

    metric: Metric
    aggregation: Aggregation
    quantile: Annotated[StrictFloat, Field(gt=0.0, lt=1.0)] | None = None
    group_by: Annotated[tuple[Dimension, ...], Field(max_length=MAX_GROUP_BY)] = ()
    time_bucket: Granularity | None = None
    filters: Annotated[tuple[FilterClause, ...], Field(max_length=MAX_FILTERS)] = ()
    time_range: TimeRange
    budget: AnalyticsBudget

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (self.aggregation is Aggregation.APPROX_QUANTILE) != (self.quantile is not None):
            raise ValueError("quantile is required for, and only for, approx_quantile")
        if self.metric is Metric.EVENTS and self.aggregation is not Aggregation.COUNT:
            raise ValueError("metric events supports only the count aggregation")
        if len(set(self.group_by)) != len(self.group_by):
            raise ValueError("group_by dimensions must be unique")
        if self.metric is Metric.COST_AMOUNT:
            pinned = any(
                f.field is Dimension.CURRENCY and f.op is not FilterOp.IS_UNKNOWN
                for f in self.filters
            )
            if not pinned and Dimension.CURRENCY not in self.group_by:
                raise ValueError("cost_amount needs a currency filter or a currency group")
        return self


class ExecutionStats(_Closed):
    rows_scanned: int = Field(ge=0)
    cost_units: Decimal = Field(ge=0)


class AggregateRow(_Closed):
    """One group. ``keys`` align with the result's ``group_by``; ``None`` key = unknown."""

    keys: tuple[str | None, ...]
    bucket: AwareDatetime | None = None
    value: Decimal | None  # None = unknown (no known value in the group), never 0
    row_count: int = Field(ge=0)  # rows in the group
    unknown_count: int = Field(ge=0)  # rows whose metric is unknown


class AggregateResult(_Closed):
    backend: str
    cloud: Cloud
    metric: Metric
    aggregation: Aggregation
    quantile: float | None = None
    group_by: tuple[Dimension, ...] = ()
    time_bucket: Granularity | None = None
    rows: tuple[AggregateRow, ...]
    stats: ExecutionStats


class CoUsageEntity(StrEnum):
    MODEL = "model"
    PROVIDER = "provider"


class CoUsageRequest(_Closed):
    """Co-usage candidate job: entities (models or providers) used in the same domain."""

    entity: CoUsageEntity = CoUsageEntity.MODEL
    min_shared_domains: Annotated[StrictInt, Field(ge=1, le=1000)] = 1
    filters: Annotated[tuple[FilterClause, ...], Field(max_length=MAX_FILTERS)] = ()
    time_range: TimeRange
    budget: AnalyticsBudget


class CoUsageCandidate(_Closed):
    """A candidate only. It still goes through evaluation and HITL (PRP-15); no rule is applied."""

    status: Literal["candidate"] = "candidate"
    entity_a: str
    entity_b: str  # entity_a < entity_b
    shared_domains: int = Field(ge=1)
    support_events: int = Field(ge=1)  # sum over shared domains of min(events_a, events_b)
    domains: tuple[str, ...]


class CoUsageResult(_Closed):
    backend: str
    cloud: Cloud
    entity: CoUsageEntity
    candidates: tuple[CoUsageCandidate, ...]
    stats: ExecutionStats
