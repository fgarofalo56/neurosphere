"""``SqlAnalytics``: the shared adapter over a ``Dialect`` plus a ``SqlExecutor``.

Vendor adapters (Items 2-4) compose or subclass this: they supply their dialect, an executor
for their endpoint, and their own cloud/host validation and migrations. Scope, plan, render,
budget enforcement, row-limit check, decoding and the co-usage job all live here.
"""

from __future__ import annotations

from decimal import Decimal

from neurosphere_core.analytics.base.co_usage import (
    aggregate_request_for,
    candidates_from_counts,
)
from neurosphere_core.analytics.base.dialect import Dialect, render_statement
from neurosphere_core.analytics.base.enforcement import (
    SqlExecutor,
    breach_error,
    run_budgeted,
)
from neurosphere_core.analytics.base.models import (
    AggregateRequest,
    AggregateResult,
    Cloud,
    CoUsageRequest,
    CoUsageResult,
    ExecutionStats,
)
from neurosphere_core.analytics.base.plan import build_plan
from neurosphere_core.analytics.base.results import build_result, decode_rows
from neurosphere_core.scope import IdentityScope


class SqlAnalytics:
    """Implements ``TelemetryAnalytics`` and ``RecommendationCompute`` over a SQL executor."""

    def __init__(
        self,
        *,
        backend: str,
        cloud: Cloud,
        dialect: Dialect,
        executor: SqlExecutor,
        schema: str | None = None,
    ) -> None:
        self.backend = backend
        self.cloud: Cloud = cloud
        self._dialect = dialect
        self._executor = executor
        self._schema = schema

    async def aggregate(
        self, request: AggregateRequest, *, scope: IdentityScope
    ) -> AggregateResult:
        plan = build_plan(request, scope, self.cloud)
        if plan.matches_nothing:  # no allowed domain: nothing to read, nothing to send
            return build_result(
                plan,
                [],
                backend=self.backend,
                cloud=self.cloud,
                stats=ExecutionStats(rows_scanned=0, cost_units=Decimal(0)),
            )
        statement = render_statement(plan, self._dialect, schema=self._schema)
        outcome = await run_budgeted(self._executor, statement, request.budget)
        if len(outcome.rows) > plan.limit:
            raise breach_error("row_limit_exceeded")
        return build_result(
            plan,
            decode_rows(plan, outcome.rows),
            backend=self.backend,
            cloud=self.cloud,
            stats=ExecutionStats(rows_scanned=outcome.rows_scanned, cost_units=outcome.cost_units),
        )

    async def co_usage_candidates(
        self, request: CoUsageRequest, *, scope: IdentityScope
    ) -> CoUsageResult:
        counts = await self.aggregate(aggregate_request_for(request), scope=scope)
        return candidates_from_counts(counts, request, backend=self.backend)
