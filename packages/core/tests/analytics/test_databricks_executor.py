"""Product Databricks executor over httpx.MockTransport (PRP-11 round 2 item 2). No network."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import httpx
import pytest
from neurosphere_core.analytics.base import BudgetBreach, ExecutionLimits, Statement
from neurosphere_core.analytics.databricks import (
    DatabricksStatementExecutor,
    ExecutorError,
    build_statement_body,
)

TOKEN = "tok-executor-unit-opaque-0123456789"  # noqa: S105 - opaque test value
LIMITS = ExecutionLimits(max_rows_scanned=5, max_cost_units=Decimal(10))


async def _token() -> str:
    return TOKEN


def _executor(handler: Any) -> tuple[DatabricksStatementExecutor, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(wrapped), base_url="https://adb-1.7.azuredatabricks.net"
    )
    return DatabricksStatementExecutor(
        client, _token, warehouse_id="0123456789abcdef", poll_interval_s=0.01
    ), seen


def _ok(rows: list[list[Any]]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "statement_id": "s1",
            "status": {"state": "SUCCEEDED"},
            "result": {"data_array": rows},
        },
    )


async def test_submit_returns_rows_and_binds_values_as_parameters() -> None:
    executor, seen = _executor(lambda r: _ok([["a", "1"]]))
    outcome = await executor.execute(Statement(sql="SELECT :p1", params=("x",)), limits=LIMITS)
    assert outcome.rows == (("a", "1"),)
    assert outcome.rows_scanned == 1
    assert outcome.cost_units == Decimal(0)
    assert seen[0].headers["authorization"] == f"Bearer {TOKEN}"
    assert b'"value":"x"' in seen[0].content.replace(b" ", b"")


async def test_polls_until_succeeded() -> None:
    states = iter(["RUNNING", "SUCCEEDED"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"statement_id": "s1", "status": {"state": "PENDING"}})
        state = next(states)
        body: dict[str, Any] = {"statement_id": "s1", "status": {"state": state}}
        if state == "SUCCEEDED":
            body["result"] = {"data_array": [["z"]]}
        return httpx.Response(200, json=body)

    executor, seen = _executor(handler)
    outcome = await executor.execute(Statement(sql="SELECT 1", params=()), limits=LIMITS)
    assert outcome.rows == (("z",),)
    assert [r.method for r in seen] == ["POST", "GET", "GET"]


async def test_cancelled_task_cancels_the_server_statement() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/cancel"):
            return httpx.Response(200, json={})
        if request.method == "POST":
            return httpx.Response(200, json={"statement_id": "s7", "status": {"state": "RUNNING"}})
        return httpx.Response(200, json={"statement_id": "s7", "status": {"state": "RUNNING"}})

    executor, seen = _executor(handler)
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.1):
            await executor.execute(Statement(sql="SELECT 1", params=()), limits=LIMITS)
    assert executor.cancelled_statements == ["s7"]
    assert any(r.url.path == "/api/2.0/sql/statements/s7/cancel" for r in seen)


async def test_row_budget_breach() -> None:
    executor, _ = _executor(lambda r: _ok([[i] for i in range(6)]))
    with pytest.raises(BudgetBreach):
        await executor.execute(Statement(sql="SELECT 1", params=()), limits=LIMITS)


async def test_http_error_carries_status_and_code_only() -> None:
    sql = "SELECT secret_column FROM hidden"
    executor, _ = _executor(
        lambda r: httpx.Response(
            403, json={"error_code": "PERMISSION_DENIED", "message": f"no {sql} {TOKEN}"}
        )
    )
    with pytest.raises(ExecutorError) as raised:
        await executor.execute(Statement(sql=sql, params=("pv",)), limits=LIMITS)
    text = str(raised.value)
    assert "403" in text
    assert "PERMISSION_DENIED" in text
    assert sql not in text
    assert TOKEN not in text
    assert "pv" not in text


async def test_failed_statement_state_reports_code_only() -> None:
    executor, _ = _executor(
        lambda r: httpx.Response(
            200,
            json={
                "statement_id": "s2",
                "status": {
                    "state": "FAILED",
                    "error": {"error_code": "BAD_REQUEST", "message": "free text secret"},
                },
            },
        )
    )
    with pytest.raises(ExecutorError) as raised:
        await executor.execute(Statement(sql="SELECT 1", params=()), limits=LIMITS)
    assert "FAILED" in str(raised.value)
    assert "secret" not in str(raised.value)


async def test_transport_error_reports_class_name_only() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connect to adb-1.7.azuredatabricks.net failed", request=request)

    executor, _ = _executor(boom)
    with pytest.raises(ExecutorError) as raised:
        await executor.execute(Statement(sql="SELECT 1", params=()), limits=LIMITS)
    assert str(raised.value) == "databricks transport error (ConnectError)"


def test_too_many_parameters_refused() -> None:
    with pytest.raises(ExecutorError):
        build_statement_body("w", "SELECT 1", tuple(range(257)))
