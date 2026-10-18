"""Budget enforcement and the executor seam (PRP-11 clarification 12).

``SqlExecutor`` is what a vendor adapter wraps (a Fabric/Synapse/Databricks connection, or the
stub). ``run_budgeted`` wraps ANY executor and enforces the request budget:

* time: ``asyncio.timeout``; expiry cancels the awaiting task, and an executor MUST abort its
  in-flight statement when that cancellation arrives;
* rows scanned and cost units: passed down as ``ExecutionLimits`` so the executor can abort
  mid-statement by raising ``BudgetBreach``, and re-checked against the reported stats;
* returned rows: checked by the adapter against ``Budget.limit`` (``row_limit_exceeded``).

Every breach raises ``RateLimitedError`` (code ``rate_limited``) with a ``reason`` naming the
exceeded budget. ADR-0007 originally said "truncation marker"; PRP-11 is the authority here:
a breach is an error, never a silently partial result. The detail never contains query text.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal, Protocol

from neurosphere_core.analytics.base.dialect import Statement
from neurosphere_core.analytics.base.models import AnalyticsBudget
from neurosphere_core.errors import DependencyTransientError, RateLimitedError

RETRY_AFTER_SECONDS: Final = 30  # documented constant: a retry should narrow the request

BreachReason = Literal[
    "time_budget_exceeded",
    "rows_scanned_budget_exceeded",
    "cost_budget_exceeded",
    "row_limit_exceeded",
]


class BudgetBreach(Exception):  # noqa: N818 - a signal consumed by run_budgeted, not an error type
    """Raised by an executor (or adapter) that detects a breach while running."""

    def __init__(self, reason: BreachReason) -> None:
        super().__init__(reason)
        self.reason: BreachReason = reason


def breach_error(reason: BreachReason) -> RateLimitedError:
    return RateLimitedError(
        RETRY_AFTER_SECONDS,
        f"analytics query budget exceeded ({reason}); the in-flight work was cancelled",
        reason=reason,
    )


@dataclass(frozen=True)
class ExecutionLimits:
    max_rows_scanned: int
    max_cost_units: Decimal


@dataclass(frozen=True)
class ExecutionOutcome:
    rows: tuple[tuple[object, ...], ...]
    rows_scanned: int
    cost_units: Decimal


class SqlExecutor(Protocol):
    """Runs a rendered statement. Contract for implementers:

    * cancellation of the awaiting task must abort the running statement and release resources
      before ``CancelledError`` propagates;
    * report ``rows_scanned`` and ``cost_units`` honestly (engine-reported where available);
    * when ``limits`` is exceeded mid-flight, abort and raise ``BudgetBreach``.
    """

    async def execute(
        self, statement: Statement, *, limits: ExecutionLimits
    ) -> ExecutionOutcome: ...


def limits_for(budget: AnalyticsBudget) -> ExecutionLimits:
    return ExecutionLimits(
        max_rows_scanned=budget.max_rows_scanned, max_cost_units=budget.max_cost_units
    )


def check_stats(rows_scanned: int, cost_units: Decimal, budget: AnalyticsBudget) -> None:
    if rows_scanned > budget.max_rows_scanned:
        raise breach_error("rows_scanned_budget_exceeded")
    if cost_units > budget.max_cost_units:
        raise breach_error("cost_budget_exceeded")


async def guarded[T](work: Callable[[], Awaitable[T]], budget: AnalyticsBudget) -> T:
    """Run ``work`` under the time budget; translate every breach into ``RateLimitedError``.

    The deadline cancels the awaiting task, so ``work`` must stop when cancelled."""
    timeout = asyncio.timeout(budget.query.timeout_ms / 1000)
    try:
        async with timeout:
            return await work()
    except BudgetBreach as breach:
        raise breach_error(breach.reason) from None
    except TimeoutError:
        if timeout.expired():
            raise breach_error("time_budget_exceeded") from None
        raise DependencyTransientError(
            "the analytics backend timed out", reason="backend_timeout"
        ) from None


async def run_budgeted(
    executor: SqlExecutor, statement: Statement, budget: AnalyticsBudget
) -> ExecutionOutcome:
    """Run ``statement`` under ``budget``; raises ``RateLimitedError`` on any breach."""
    outcome = await guarded(lambda: executor.execute(statement, limits=limits_for(budget)), budget)
    check_stats(outcome.rows_scanned, outcome.cost_units, budget)
    return outcome
