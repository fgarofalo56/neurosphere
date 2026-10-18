"""Budget enforcement: every breach raises rate_limited and the in-flight work really stops."""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal

import pytest
from neurosphere_core.analytics.base import (
    RETRY_AFTER_SECONDS,
    AnsiDialect,
    BudgetBreach,
    Dimension,
    ExecutionLimits,
    ExecutionOutcome,
    FunctionShim,
    RewriteRule,
    Shim,
    SqlAnalytics,
    Statement,
    StubSqlEndpoint,
    standard_shims,
)
from neurosphere_core.analytics.base.enforcement import run_budgeted
from neurosphere_core.analytics.fixture import build_dataset
from neurosphere_core.errors import RateLimitedError

from .analytics_helpers import (
    fixture_adapter,
    make_budget,
    make_request,
    make_scope,
    stub_adapter,
)

STATEMENT = Statement(sql="SELECT 1", params=())


class SlowExecutor:
    """Fake executor that would run for ten seconds unless cancelled."""

    def __init__(self) -> None:
        self.started = False
        self.cancelled = False
        self.finished = False

    async def execute(self, statement: Statement, *, limits: ExecutionLimits) -> ExecutionOutcome:
        self.started = True
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        self.finished = True
        return ExecutionOutcome(rows=(), rows_scanned=0, cost_units=Decimal(0))


class StatsExecutor:
    def __init__(self, rows_scanned: int, cost_units: str) -> None:
        self._outcome = ExecutionOutcome((), rows_scanned, Decimal(cost_units))

    async def execute(self, statement: Statement, *, limits: ExecutionLimits) -> ExecutionOutcome:
        return self._outcome


async def test_time_budget_cancels_slow_executor() -> None:
    executor = SlowExecutor()
    started = time.perf_counter()
    with pytest.raises(RateLimitedError) as err:
        await run_budgeted(executor, STATEMENT, make_budget(timeout_ms=50))
    assert time.perf_counter() - started < 2
    assert executor.started and executor.cancelled and not executor.finished
    assert err.value.code == "rate_limited"
    assert err.value.reason == "time_budget_exceeded"
    assert err.value.retry_after_seconds == RETRY_AFTER_SECONDS
    assert "SELECT" not in (err.value.detail or "")  # no query text in the error
    err.value.to_problem_details("corr-1")  # renders a valid contract body


async def test_reported_stats_over_budget_raise() -> None:
    with pytest.raises(RateLimitedError) as rows:
        await run_budgeted(StatsExecutor(11, "0"), STATEMENT, make_budget(max_rows_scanned=10))
    assert rows.value.reason == "rows_scanned_budget_exceeded"
    with pytest.raises(RateLimitedError) as cost:
        await run_budgeted(StatsExecutor(1, "5.5"), STATEMENT, make_budget(max_cost_units="5"))
    assert cost.value.reason == "cost_budget_exceeded"
    ok = await run_budgeted(StatsExecutor(10, "5"), STATEMENT, make_budget(max_rows_scanned=10))
    assert ok.rows_scanned == 10


async def test_executor_breach_is_translated() -> None:
    class Breaching:
        async def execute(
            self, statement: Statement, *, limits: ExecutionLimits
        ) -> ExecutionOutcome:
            raise BudgetBreach("cost_budget_exceeded")

    with pytest.raises(RateLimitedError) as err:
        await run_budgeted(Breaching(), STATEMENT, make_budget())
    assert err.value.reason == "cost_budget_exceeded"


def _slow_shim() -> Shim:
    return Shim(
        name="slow-test",
        description="test only: sleeps 5 ms per row evaluated",
        rules=(RewriteRule("slow-where", r"\bWHERE\b", "WHERE NS_SLOW() AND"),),
        functions=(FunctionShim("NS_SLOW", 0, lambda: time.sleep(0.005) or 1, False),),
    )


async def test_stub_time_budget_aborts_running_statement() -> None:
    records = build_dataset("commercial", 720)  # 720 rows x 5 ms would be about 3.6 s
    endpoint = StubSqlEndpoint(records, shims=(*standard_shims(), _slow_shim()))
    adapter = SqlAnalytics(
        backend="stub", cloud="commercial", dialect=AnsiDialect(), executor=endpoint
    )
    started = time.perf_counter()
    with pytest.raises(RateLimitedError) as err:
        await adapter.aggregate(
            make_request(budget=make_budget(timeout_ms=100)), scope=make_scope()
        )
    assert err.value.reason == "time_budget_exceeded"
    assert time.perf_counter() - started < 1.5  # aborted, not run to completion
    assert 0 < endpoint.last_rows_processed < len(records)
    # the worker thread has really stopped: the statement lock is free again
    assert endpoint._lock.acquire(blocking=False)  # pyright: ignore[reportPrivateUsage]
    endpoint._lock.release()  # pyright: ignore[reportPrivateUsage]


async def test_stub_rows_scanned_budget_aborts_mid_flight() -> None:
    adapter, endpoint = stub_adapter(build_dataset("commercial", 720))
    with pytest.raises(RateLimitedError) as err:
        await adapter.aggregate(
            make_request(budget=make_budget(max_rows_scanned=100)), scope=make_scope()
        )
    assert err.value.reason == "rows_scanned_budget_exceeded"
    assert endpoint.last_rows_processed <= 101


async def test_stub_cost_budget_aborts_mid_flight() -> None:
    adapter, endpoint = stub_adapter(build_dataset("commercial", 720))
    with pytest.raises(RateLimitedError) as err:
        await adapter.aggregate(
            make_request(budget=make_budget(max_cost_units="0.05")), scope=make_scope()
        )
    assert err.value.reason == "cost_budget_exceeded"
    assert endpoint.last_rows_processed <= 51


async def test_stub_row_limit_is_a_breach_not_truncation() -> None:
    adapter, _ = stub_adapter(build_dataset("commercial", 720))
    request = make_request(
        group_by=(Dimension.MODEL, Dimension.DOMAIN_ID), budget=make_budget(limit=2)
    )
    with pytest.raises(RateLimitedError) as err:
        await adapter.aggregate(request, scope=make_scope())
    assert err.value.reason == "row_limit_exceeded"


async def test_fixture_budgets_raise_rate_limited() -> None:
    adapter = fixture_adapter()
    cases = [
        (make_budget(max_rows_scanned=10), "rows_scanned_budget_exceeded"),
        (make_budget(max_cost_units="0.01"), "cost_budget_exceeded"),
        (make_budget(limit=1), "row_limit_exceeded"),
    ]
    for budget, reason in cases:
        request = make_request(group_by=(Dimension.MODEL,), budget=budget)
        with pytest.raises(RateLimitedError) as err:
            await adapter.aggregate(request, scope=make_scope())
        assert err.value.reason == reason


async def test_fixture_time_budget_cancels_the_scan() -> None:
    adapter = fixture_adapter(scan_delay_s=0.1)  # 11 chunks x 0.1 s if it were not cancelled
    started = time.perf_counter()
    with pytest.raises(RateLimitedError) as err:
        await adapter.aggregate(make_request(budget=make_budget(timeout_ms=50)), scope=make_scope())
    assert err.value.reason == "time_budget_exceeded"
    assert time.perf_counter() - started < 0.6
