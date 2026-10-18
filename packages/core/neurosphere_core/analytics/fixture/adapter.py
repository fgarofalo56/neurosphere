"""In-process fixture adapter (PRP-11 item 1): sandbox only, no SQL.

Evaluates the shared ``QueryPlan`` directly in Python over normalized records. It is the
reference the vendor adapters are compared against (``compare_results``) and it enforces the
same budgets as every adapter: the scan runs as cancellable async work, so exceeding the time,
rows-scanned, cost or returned-row budget stops the scan and raises ``rate_limited``.

Sandbox-only: construction is refused unless ``sandbox=True`` is passed or ``NS_ENV=local``
(the unset default), the same switch the client factories use for emulators.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from math import ceil
from typing import Final

from pydantic import ValidationError

from neurosphere_core.analytics.base.co_usage import (
    aggregate_request_for,
    candidates_from_counts,
)
from neurosphere_core.analytics.base.enforcement import (
    BudgetBreach,
    breach_error,
    guarded,
)
from neurosphere_core.analytics.base.models import (
    AggregateRequest,
    AggregateResult,
    AggregateRow,
    Aggregation,
    Cloud,
    CoUsageRequest,
    CoUsageResult,
    ExecutionStats,
    FilterOp,
    Granularity,
)
from neurosphere_core.analytics.base.plan import (
    DIMENSION_COLUMN,
    METRIC_COLUMN,
    Predicate,
    QueryPlan,
    build_plan,
)
from neurosphere_core.analytics.base.records import AnalyticsRecord
from neurosphere_core.analytics.base.results import build_result
from neurosphere_core.analytics.base.stub import DEFAULT_COST_UNITS_PER_ROW
from neurosphere_core.cloud.settings import load_settings
from neurosphere_core.errors import ForbiddenError
from neurosphere_core.scope import IdentityScope

SCAN_CHUNK: Final = 64  # rows between cooperative yields (and budget checks)


def _sandbox_allowed(sandbox: bool) -> bool:
    if sandbox:
        return True
    try:
        return load_settings().env == "local"
    except ValidationError:
        return False


def _matches(record: AnalyticsRecord, pred: Predicate) -> bool:
    value = getattr(record, pred.column.value)
    match pred.op:
        case FilterOp.EQ:
            return value is not None and value == pred.values[0]
        case FilterOp.IN:
            return value is not None and value in pred.values
        case FilterOp.IS_UNKNOWN:
            return value is None
    return False  # pragma: no cover


def _bucket(value: datetime, granularity: Granularity) -> datetime:
    value = value.astimezone(UTC)
    if granularity is Granularity.HOUR:
        return value.replace(minute=0, second=0, microsecond=0)
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def _quantile(values: list[Decimal], q: Decimal) -> Decimal:
    """Exact nearest-rank quantile: the stub shim and the documented tolerance share it."""
    ordered = sorted(values)
    return ordered[max(ceil(q * len(ordered)), 1) - 1]


def _aggregate(plan: QueryPlan, members: list[AnalyticsRecord]) -> tuple[Decimal | None, int]:
    column = METRIC_COLUMN[plan.metric]
    if column is None:
        return Decimal(len(members)), len(members)
    known = [Decimal(v) for r in members if (v := getattr(r, column.value)) is not None]
    value: Decimal | None
    if plan.aggregation is Aggregation.COUNT:
        value = Decimal(len(known))
    elif not known:
        value = None  # unknown, never 0
    elif plan.aggregation is Aggregation.SUM:
        value = sum(known, Decimal(0))
    elif plan.aggregation is Aggregation.MIN:
        value = min(known)
    elif plan.aggregation is Aggregation.MAX:
        value = max(known)
    else:
        assert plan.quantile is not None
        value = _quantile(known, plan.quantile)
    return value, len(known)


class FixtureAnalytics:
    """``TelemetryAnalytics`` and ``RecommendationCompute`` over in-memory synthetic records."""

    backend = "fixture"

    def __init__(
        self,
        records: Sequence[AnalyticsRecord],
        *,
        cloud: Cloud,
        sandbox: bool = False,
        cost_units_per_row: Decimal = DEFAULT_COST_UNITS_PER_ROW,
        scan_delay_s: float = 0.0,
    ) -> None:
        if not _sandbox_allowed(sandbox):
            raise ForbiddenError(
                "the fixture analytics adapter is sandbox-only (set sandbox=True or NS_ENV=local)",
                reason="fixture_sandbox_only",
            )
        mixed = {r.cloud for r in records} - {cloud}
        if mixed:
            raise ValueError(f"records from another cloud ({sorted(mixed)}) must not be loaded")
        self.cloud: Cloud = cloud
        self._records = tuple(records)
        self._cost_per_row = cost_units_per_row
        self._scan_delay_s = scan_delay_s  # test hook: makes the scan slow and cancellable

    async def _scan(self, plan: QueryPlan, request: AggregateRequest) -> list[AnalyticsRecord]:
        budget = request.budget
        matched: list[AnalyticsRecord] = []
        for n, record in enumerate(self._records, start=1):
            if n % SCAN_CHUNK == 0:
                await asyncio.sleep(self._scan_delay_s)  # cancellation point
            if n > budget.max_rows_scanned:
                raise BudgetBreach("rows_scanned_budget_exceeded")
            if self._cost_per_row * n > budget.max_cost_units:
                raise BudgetBreach("cost_budget_exceeded")
            if plan.time_start <= record.event_time < plan.time_end and all(
                _matches(record, p) for p in plan.predicates
            ):
                matched.append(record)
        return matched

    async def aggregate(
        self, request: AggregateRequest, *, scope: IdentityScope
    ) -> AggregateResult:
        plan = build_plan(request, scope, self.cloud)
        if plan.matches_nothing:
            return build_result(
                plan,
                [],
                backend=self.backend,
                cloud=self.cloud,
                stats=ExecutionStats(rows_scanned=0, cost_units=Decimal(0)),
            )
        matched = await guarded(lambda: self._scan(plan, request), request.budget)
        groups: dict[tuple[object, ...], list[AnalyticsRecord]] = defaultdict(list)
        for record in matched:
            key: tuple[object, ...] = tuple(
                getattr(record, DIMENSION_COLUMN[d].value) for d in plan.group_by
            )
            if plan.time_bucket is not None:
                key = (*key, _bucket(record.event_time, plan.time_bucket))
            groups[key].append(record)
        rows: list[AggregateRow] = []
        for key, members in groups.items():
            value, known = _aggregate(plan, members)
            n_keys = len(plan.group_by)
            rows.append(
                AggregateRow(
                    keys=tuple(None if k is None else str(k) for k in key[:n_keys]),
                    bucket=key[n_keys] if plan.time_bucket is not None else None,  # type: ignore[arg-type]
                    value=value,
                    row_count=len(members),
                    unknown_count=len(members) - known,
                )
            )
        if len(rows) > plan.limit:
            raise breach_error("row_limit_exceeded")
        total = len(self._records)
        return build_result(
            plan,
            rows,
            backend=self.backend,
            cloud=self.cloud,
            stats=ExecutionStats(rows_scanned=total, cost_units=self._cost_per_row * total),
        )

    async def co_usage_candidates(
        self, request: CoUsageRequest, *, scope: IdentityScope
    ) -> CoUsageResult:
        counts = await self.aggregate(aggregate_request_for(request), scope=scope)
        return candidates_from_counts(counts, request, backend=self.backend)


__all__ = ["FixtureAnalytics"]
