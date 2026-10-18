"""G01 analytics gate: the Databricks Statement Execution executor and the workload driver.

httpx.MockTransport only: no network. The workload test swaps the live executor for a fake that
delegates SELECTs to the SQLite stub, so the whole create-migrate-load-compare-drop flow runs.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from neurosphere_core.analytics.base import (
    AnalyticsBudget,
    BudgetBreach,
    ExecutionLimits,
    ExecutionOutcome,
    Statement,
    StubSqlEndpoint,
    run_budgeted,
)
from neurosphere_core.analytics.databricks import DatabricksConfig, sqlite_shims
from neurosphere_core.analytics.fixture import build_dataset
from neurosphere_core.errors import RateLimitedError

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gates" / "g01_analytics_live.py"
FAKE_TOKEN = "tok-unit-test-opaque-0123456789"
LIMITS = ExecutionLimits(max_rows_scanned=1000, max_cost_units=Decimal(1000))
HOST = "adb-1234567890123456.7.azuredatabricks.net"
RUN_ID = "abcdef012345"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("g01_analytics_dbx_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["g01_analytics_dbx_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


async def token() -> str:
    return FAKE_TOKEN


class Server:
    """A scripted Statement Execution API: records requests, answers from ``responder``."""

    def __init__(self, responder: Any) -> None:
        self.requests: list[httpx.Request] = []
        self.responder = responder

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responder(request)

    def executor(self, mod: ModuleType) -> Any:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(self.handler), base_url=f"https://{HOST}"
        )
        return mod.DatabricksStatementExecutor(
            client, token, warehouse_id="0123456789abcdef", poll_interval_s=0.01
        )

    def bodies(self) -> list[dict[str, Any]]:
        return [
            json.loads(r.content)
            for r in self.requests
            if r.method == "POST" and r.url.path == "/api/2.0/sql/statements"
        ]


def succeeded(rows: list[list[Any]]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "statement_id": "stmt-1",
            "status": {"state": "SUCCEEDED"},
            "manifest": {"total_row_count": len(rows)},
            "result": {"data_array": rows},
        },
    )


# ----------------------------------------------------------------------------- request shape


async def test_named_parameters_and_values_never_in_statement_text() -> None:
    mod = load()
    server = Server(lambda r: succeeded([["a", "2"]]))
    executor = server.executor(mod)
    sql = "SELECT `model`, COUNT(*) FROM `c`.`s`.`t` WHERE `currency` = :p1 AND `n` > :p2"
    secret_looking_value = "value-that-must-not-leak-into-sql"
    outcome = await executor.execute(
        Statement(sql=sql, params=(secret_looking_value, 7)), limits=LIMITS
    )
    assert outcome.rows == (("a", "2"),)
    (body,) = server.bodies()
    assert body["statement"] == sql
    assert secret_looking_value not in body["statement"]
    assert body["parameters"] == [
        {"name": "p1", "type": "STRING", "value": secret_looking_value},
        {"name": "p2", "type": "BIGINT", "value": "7"},
    ]
    assert body["warehouse_id"] == "0123456789abcdef"
    assert body["wait_timeout"] == "0s"  # async submit: a statement id exists before any wait
    assert body["disposition"] == "INLINE"
    assert server.requests[0].headers["authorization"] == f"Bearer {FAKE_TOKEN}"


async def test_null_parameter_has_no_value_and_decimal_is_plain_text() -> None:
    mod = load()
    body = mod.build_statement_body("w", "SELECT :p1, :p2", (None, Decimal("0.000100000000")))
    assert body["parameters"][0] == {"name": "p1", "type": "STRING"}
    assert body["parameters"][1] == {
        "name": "p2",
        "type": "DECIMAL(38,12)",
        "value": "0.000100000000",
    }


async def test_polls_until_succeeded() -> None:
    mod = load()
    states = iter(["RUNNING", "RUNNING", "SUCCEEDED"])

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"statement_id": "s9", "status": {"state": "PENDING"}})
        state = next(states)
        body: dict[str, Any] = {"statement_id": "s9", "status": {"state": state}}
        if state == "SUCCEEDED":
            body["result"] = {"data_array": [["1"]]}
        return httpx.Response(200, json=body)

    server = Server(respond)
    outcome = await server.executor(mod).execute(Statement("SELECT 1", ()), limits=LIMITS)
    assert outcome.rows == (("1",),)
    assert [r.method for r in server.requests] == ["POST", "GET", "GET", "GET"]


# ----------------------------------------------------------------------------- cancel / budgets


def budget(timeout_ms: int) -> AnalyticsBudget:
    from neurosphere_contracts.query.v1.budget import Budget

    return AnalyticsBudget(
        query=Budget(timeout_ms=timeout_ms, limit=10, max_depth=0),
        max_rows_scanned=1000,
        max_cost_units=Decimal(1000),
    )


async def test_time_budget_cancels_the_server_side_statement() -> None:
    mod = load()

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/cancel"):
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"statement_id": "slow-1", "status": {"state": "RUNNING"}})

    server = Server(respond)
    executor = server.executor(mod)
    with pytest.raises(RateLimitedError) as breach:
        await run_budgeted(executor, Statement("SELECT 1", ()), budget(60))
    assert breach.value.code == "rate_limited"
    cancels = [r for r in server.requests if r.url.path.endswith("/cancel")]
    assert [r.url.path for r in cancels] == ["/api/2.0/sql/statements/slow-1/cancel"]
    assert executor.cancelled_statements == ["slow-1"]
    assert cancels[0].method == "POST"


async def test_rows_budget_breach_is_a_budget_breach() -> None:
    mod = load()
    server = Server(lambda r: succeeded([[str(i)] for i in range(5)]))
    tight = ExecutionLimits(max_rows_scanned=3, max_cost_units=Decimal(1))
    with pytest.raises(BudgetBreach) as breach:
        await server.executor(mod).execute(Statement("SELECT 1", ()), limits=tight)
    assert breach.value.reason == "rows_scanned_budget_exceeded"


async def test_chunked_result_is_refused_not_truncated() -> None:
    mod = load()
    body = {
        "statement_id": "s",
        "status": {"state": "SUCCEEDED"},
        "result": {"data_array": [["1"]], "next_chunk_internal_link": "/x"},
    }
    server = Server(lambda r: httpx.Response(200, json=body))
    with pytest.raises(mod.ExecutorError):
        await server.executor(mod).execute(Statement("SELECT 1", ()), limits=LIMITS)


# ----------------------------------------------------------------------------- no leaks


async def test_token_never_appears_in_errors() -> None:
    mod = load()

    # A hostile server that echoes the Authorization header and the statement in its error.
    def echo(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={
                "error_code": "INTERNAL_ERROR",
                "message": f"{request.headers['authorization']} {request.content.decode()}",
            },
        )

    server = Server(echo)
    with pytest.raises(mod.ExecutorError) as raised:
        await server.executor(mod).execute(Statement("SELECT secretish", ("v",)), limits=LIMITS)
    text = str(raised.value)
    assert FAKE_TOKEN not in text
    assert "SELECT" not in text
    assert "HTTP 500" in text
    assert "INTERNAL_ERROR" in text


async def test_transport_error_text_is_not_echoed() -> None:
    mod = load()

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.headers['authorization']}")

    with pytest.raises(mod.ExecutorError) as raised:
        await Server(boom).executor(mod).execute(Statement("SELECT 1", ()), limits=LIMITS)
    assert FAKE_TOKEN not in str(raised.value)
    assert "ConnectError" in str(raised.value)


async def test_failed_statement_reports_only_the_code() -> None:
    mod = load()
    body = {
        "statement_id": "s",
        "status": {
            "state": "FAILED",
            "error": {"error_code": "BAD_REQUEST", "message": "near SELECT secretish"},
        },
    }
    server = Server(lambda r: httpx.Response(200, json=body))
    with pytest.raises(mod.ExecutorError) as raised:
        await server.executor(mod).execute(Statement("SELECT 1", ()), limits=LIMITS)
    assert "FAILED" in str(raised.value)
    assert "BAD_REQUEST" in str(raised.value)
    assert "secretish" not in str(raised.value)


# ----------------------------------------------------------------------------- insert builder


def test_insert_statements_batch_and_bind_values_only_as_parameters() -> None:
    mod = load()
    records = build_dataset("commercial", 40)
    statements = mod.insert_statements("main", "ns_g01a_x", records)
    assert len(statements) == 3  # 15 + 15 + 10
    for sql, params in statements:
        assert len(params) <= mod.MAX_PARAMETERS
        assert "`main`.`ns_g01a_x`.`ns_analytics_events`" in sql
        assert "commercial-" not in sql  # no value text in the statement
        assert sql.count(":p") == len(params)
    first_params = statements[0][1]
    assert first_params[0] == records[0].event_id
    assert first_params[1].endswith("Z")


# ----------------------------------------------------------------------------- workload


class FakeLive:
    """Stands in for the Databricks API: DDL/DML are recorded, SELECTs run on the SQLite stub."""

    def __init__(self, endpoint: StubSqlEndpoint, *, fail_on_insert: int | None = None) -> None:
        self.endpoint = endpoint
        self.sql: list[str] = []
        self.fail_on_insert = fail_on_insert
        self.inserts = 0

    async def execute(self, statement: Statement, *, limits: ExecutionLimits) -> ExecutionOutcome:
        self.sql.append(statement.sql)
        text = statement.sql.lstrip()
        if text.startswith("INSERT INTO `main`"):
            self.inserts += 1
            if self.fail_on_insert is not None and self.inserts >= self.fail_on_insert:
                raise RuntimeError("insert failed")
        if text.startswith("SELECT") and "ns_analytics_events" in text:
            return await self.endpoint.execute(statement, limits=limits)
        return ExecutionOutcome(rows=(), rows_scanned=0, cost_units=Decimal(0))


def settings(mod: ModuleType) -> Any:
    return mod.AdapterSettings(
        name="databricks",
        region="eastus2",
        sku_class="serverless-test",
        config={"host": HOST, "warehouse_id": "0123456789abcdef", "catalog": "main"},
    )


def fake_live() -> FakeLive:
    config = DatabricksConfig.model_validate(
        {
            "cloud": "commercial",
            "region": "eastus2",
            "workspace_host": HOST,
            "warehouse_id": "0123456789abcdef",
            "catalog": "main",
            "schema_name": f"ns_g01a_{RUN_ID}",
        }
    )
    endpoint = StubSqlEndpoint(
        build_dataset("commercial"), shims=sqlite_shims(config), schema=config.schema_name
    )
    return FakeLive(endpoint)


def options(mod: ModuleType, *, keep: bool = False) -> Any:
    return mod.RunOptions(operator="unit", keep=keep, run_id=RUN_ID, timeout_ms=5000)


async def test_full_workload_passes_against_an_equivalent_backend() -> None:
    mod = load()
    live = fake_live()
    result = await mod.run_databricks(settings(mod), options(mod), executor=live)
    assert result.status == "PASS", result.reason
    assert len(result.cases) == 14
    assert all(c["status"] == "PASS" for c in result.cases)
    assert all(c["live_vs_stub"]["equivalent"] for c in result.cases)
    kinds = {c["kind"] for c in result.cases}
    assert kinds == {"exact", "approx_quantile"}
    assert result.stub_shims and all(s["name"] and s["rule"] for s in result.stub_shims)
    # order: schema, migrations, load, queries, drop
    assert live.sql[0].startswith(f"CREATE SCHEMA IF NOT EXISTS `main`.`ns_g01a_{RUN_ID}`")
    assert any(s.startswith("INSERT INTO `main`") for s in live.sql)
    assert live.sql[-1] == f"DROP SCHEMA IF EXISTS `main`.`ns_g01a_{RUN_ID}` CASCADE"
    assert result.teardown == {"status": "DROPPED"}


async def test_keep_skips_the_drop() -> None:
    mod = load()
    live = fake_live()
    result = await mod.run_databricks(settings(mod), options(mod, keep=True), executor=live)
    assert result.status == "PASS"
    assert not any("DROP SCHEMA" in s for s in live.sql)
    assert result.teardown["status"] == "KEPT"


async def test_setup_failure_is_fail_and_still_drops_the_schema() -> None:
    mod = load()
    live = fake_live()
    live.fail_on_insert = 2
    result = await mod.run_databricks(settings(mod), options(mod), executor=live)
    assert result.status == "FAIL"
    assert "setup failed" in result.reason
    assert result.cases == []
    assert live.sql[-1].startswith("DROP SCHEMA IF EXISTS")


async def test_a_diverging_backend_fails_the_case_and_records_the_delta() -> None:
    mod = load()
    live = fake_live()
    real = live.endpoint.execute

    async def skewed(statement: Statement, *, limits: ExecutionLimits) -> ExecutionOutcome:
        out = await real(statement, limits=limits)
        if "COUNT(*)" in statement.sql and " GROUP BY " not in statement.sql:
            first = list(out.rows[0])
            first[0] = int(str(first[0])) + 1  # an exact count that is off by one
            return ExecutionOutcome(
                rows=(tuple(first), *out.rows[1:]),
                rows_scanned=out.rows_scanned,
                cost_units=out.cost_units,
            )
        return out

    live.endpoint.execute = skewed  # type: ignore[method-assign]
    result = await mod.run_databricks(settings(mod), options(mod), executor=live)
    assert result.status == "FAIL"
    failed = [c for c in result.cases if c["status"] == "FAIL"]
    assert failed
    assert failed[0]["tolerance_result"] == "mismatch"
    assert failed[0]["mismatches"]
    assert failed[0]["live_vs_stub"]["equivalent"] is False


async def test_budget_timeout_applies_to_every_request() -> None:
    mod = load()
    live = fake_live()
    real = live.endpoint.execute

    async def slow(statement: Statement, *, limits: ExecutionLimits) -> ExecutionOutcome:
        await asyncio.sleep(5)
        return await real(statement, limits=limits)

    live.endpoint.execute = slow  # type: ignore[method-assign]
    fast = mod.RunOptions(operator="u", keep=False, run_id=RUN_ID, timeout_ms=1000)
    result = await mod.run_databricks(settings(mod), fast, executor=live)
    assert result.status == "FAIL"
    assert all(c["status"] == "FAIL" for c in result.cases)
    assert any("RateLimited" in c.get("error", "") for c in result.cases)
