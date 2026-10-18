"""Dialect-neutral query plan, built only from the closed enums plus the server-derived scope.

The plan is the single place where authorization becomes predicates: customer, cloud and
allowed domains are ALWAYS the first predicates, whatever the caller asked. Caller filters are
ANDed after them, so they can only narrow. Adapters (SQL renderer, fixture evaluator) consume
the plan and never the raw request.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from neurosphere_core.analytics.base.models import (
    AggregateRequest,
    Aggregation,
    Cloud,
    Dimension,
    FilterOp,
    Granularity,
    Metric,
)
from neurosphere_core.errors import ForbiddenError
from neurosphere_core.scope import IdentityScope


class Column(StrEnum):
    """The fixed physical column whitelist; values are the only identifiers ever rendered."""

    EVENT_TIME = "event_time"
    CLOUD = "cloud"
    CUSTOMER_ID = "customer_id"
    DOMAIN_ID = "domain_id"
    PROVIDER = "provider"
    MODEL = "model"
    SPAN_KIND = "span_kind"
    OUTCOME = "outcome"
    CURRENCY = "currency"
    DURATION_MS = "duration_ms"
    INPUT_TOKENS = "input_tokens"
    OUTPUT_TOKENS = "output_tokens"
    COST_AMOUNT = "cost_amount"
    EVENT_ID = "event_id"


DIMENSION_COLUMN: dict[Dimension, Column] = {d: Column(d.value) for d in Dimension}
METRIC_COLUMN: dict[Metric, Column | None] = {
    Metric.EVENTS: None,
    Metric.COST_AMOUNT: Column.COST_AMOUNT,
    Metric.INPUT_TOKENS: Column.INPUT_TOKENS,
    Metric.OUTPUT_TOKENS: Column.OUTPUT_TOKENS,
    Metric.DURATION_MS: Column.DURATION_MS,
}


@dataclass(frozen=True)
class Predicate:
    column: Column
    op: FilterOp
    values: tuple[str, ...]


@dataclass(frozen=True)
class QueryPlan:
    cloud: Cloud
    metric: Metric
    aggregation: Aggregation
    quantile: Decimal | None
    group_by: tuple[Dimension, ...]
    time_bucket: Granularity | None
    predicates: tuple[Predicate, ...]
    time_start: datetime  # UTC, inclusive
    time_end: datetime  # UTC, exclusive
    limit: int

    @property
    def matches_nothing(self) -> bool:
        """True when the scope grants no domain: no query is sent and the result is empty."""
        return any(p.op is FilterOp.IN and not p.values for p in self.predicates)


def check_scope(scope: object, adapter_cloud: Cloud) -> IdentityScope:
    """Refuse anything that is not a server-derived scope, or one from another cloud."""
    if not isinstance(scope, IdentityScope):
        raise ForbiddenError("a server-derived IdentityScope is required", reason="scope_required")
    if scope.cloud != adapter_cloud:
        raise ForbiddenError(
            f"scope cloud {scope.cloud} does not match adapter cloud {adapter_cloud}",
            reason="cloud_mismatch",
        )
    return scope


def build_plan(request: AggregateRequest, scope: IdentityScope, cloud: Cloud) -> QueryPlan:
    scope = check_scope(scope, cloud)
    predicates = [
        Predicate(Column.CUSTOMER_ID, FilterOp.EQ, (scope.customer_id,)),
        Predicate(Column.CLOUD, FilterOp.EQ, (cloud,)),
        Predicate(Column.DOMAIN_ID, FilterOp.IN, tuple(sorted(set(scope.allowed_domains)))),
        *(Predicate(DIMENSION_COLUMN[f.field], f.op, tuple(f.values)) for f in request.filters),
    ]
    return QueryPlan(
        cloud=cloud,
        metric=request.metric,
        aggregation=request.aggregation,
        quantile=Decimal(str(request.quantile)) if request.quantile is not None else None,
        group_by=request.group_by,
        time_bucket=request.time_bucket,
        predicates=tuple(predicates),
        time_start=request.time_range.start,
        time_end=request.time_range.end,
        limit=request.budget.query.limit,
    )
