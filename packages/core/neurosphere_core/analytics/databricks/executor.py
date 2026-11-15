"""Databricks SQL Statement Execution API executor (PRP-11 round 2, item 2).

Moved from ``scripts/gates/g01_analytics_live.py`` so the API runtime and the live gate use one
class. ``httpx`` plus an Entra bearer token. Errors carry the HTTP status or the API
``error_code`` only: never query text, bound values, hosts or tokens.

The Entra resource id is the Azure Databricks application (verified on Learn 2026-10-18 for
Commercial; Government is unverified, see ``analytics_government_unverified``).
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

from neurosphere_core.analytics.base import BudgetBreach, ExecutionOutcome

DATABRICKS_RESOURCE_ID = "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d"
DATABRICKS_SCOPE = f"{DATABRICKS_RESOURCE_ID}/.default"
STATEMENTS_PATH = "/api/2.0/sql/statements"
MAX_PARAMETERS = 256  # Statement Execution API limit on parameters per statement (unverified)

TokenProvider = Callable[[], Awaitable[str]]

_ERROR_CODE = re.compile(r"[A-Z_]{1,64}")


class ExecutorError(RuntimeError):
    """A statement failed. The message never carries query text, values or credentials."""


def _param_type(value: object) -> str:
    if isinstance(value, bool):
        return "BOOLEAN"
    if isinstance(value, int):
        return "BIGINT"
    if isinstance(value, Decimal):
        return "DECIMAL(38,12)"
    if isinstance(value, float):
        return "DOUBLE"
    return "STRING"


def build_statement_body(
    warehouse_id: str, sql: str, params: Sequence[object], *, wait_timeout: str = "0s"
) -> dict[str, Any]:
    """Statement Execution API request body. Values travel ONLY in ``parameters`` as named
    entries ``p1..pN`` matching the ``:pN`` markers; they are never interpolated into ``sql``."""
    if len(params) > MAX_PARAMETERS:
        raise ExecutorError("too many bound parameters for one statement")
    parameters: list[dict[str, Any]] = []
    for index, value in enumerate(params, start=1):
        entry: dict[str, Any] = {"name": f"p{index}", "type": _param_type(value)}
        if value is not None:
            entry["value"] = format(value, "f") if isinstance(value, Decimal) else str(value)
        parameters.append(entry)
    return {
        "warehouse_id": warehouse_id,
        "statement": sql,
        "parameters": parameters,
        # "0s" = asynchronous submit: the statement id is known immediately, so a cancellation
        # (budget or timeout) can always cancel the server-side statement.
        "wait_timeout": wait_timeout,
        "disposition": "INLINE",
        "format": "JSON_ARRAY",
    }


def _safe_code(raw: object) -> str:
    code = str(raw) if raw else ""
    return code if _ERROR_CODE.fullmatch(code) else "unspecified"


class DatabricksStatementExecutor:
    """``SqlExecutor`` over the Databricks SQL Statement Execution API (httpx, Entra bearer).

    * cancellation of the awaiting task (time budget) cancels the server-side statement;
    * the engine does not report rows scanned or cost via this API: ``rows_scanned`` is the
      returned row count (a lower bound) and ``cost_units`` is 0, a documented G12 gap;
    * errors carry the HTTP status or the API ``error_code`` only: no query text, value or token.
    """

    def __init__(
        self,
        client: Any,
        token_provider: TokenProvider,
        *,
        warehouse_id: str,
        poll_interval_s: float = 1.0,
    ) -> None:
        self._client = client
        self._token = token_provider
        self._warehouse_id = warehouse_id
        self._poll = poll_interval_s
        self.cancelled_statements: list[str] = []

    async def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {await self._token()}"}

    @staticmethod
    def _payload(response: Any) -> dict[str, Any]:
        status = int(response.status_code)
        try:
            data = response.json()
        except ValueError:
            data = {}
        if status >= 400:
            code = _safe_code(data.get("error_code")) if isinstance(data, dict) else "unspecified"  # pyright: ignore[reportUnknownMemberType]
            raise ExecutorError(f"databricks API returned HTTP {status} ({code})")
        if not isinstance(data, dict):
            raise ExecutorError("databricks API returned an unexpected payload")
        return data  # pyright: ignore[reportUnknownVariableType]

    async def _cancel(self, statement_id: str) -> None:
        self.cancelled_statements.append(statement_id)
        with contextlib.suppress(Exception):
            await self._client.post(
                f"{STATEMENTS_PATH}/{statement_id}/cancel", headers=await self._headers()
            )

    async def execute(self, statement: Any, *, limits: Any) -> Any:
        body = build_statement_body(self._warehouse_id, statement.sql, statement.params)
        statement_id: str | None = None
        try:
            payload = self._payload(
                await self._client.post(STATEMENTS_PATH, json=body, headers=await self._headers())
            )
            statement_id = str(payload.get("statement_id", ""))
            if not statement_id:
                raise ExecutorError("databricks API returned no statement id")
            state = str(payload.get("status", {}).get("state", ""))
            while state in ("PENDING", "RUNNING"):
                await asyncio.sleep(self._poll)
                payload = self._payload(
                    await self._client.get(
                        f"{STATEMENTS_PATH}/{statement_id}", headers=await self._headers()
                    )
                )
                state = str(payload.get("status", {}).get("state", ""))
        except asyncio.CancelledError:
            if statement_id:
                await self._cancel(statement_id)
            raise
        except ExecutorError:
            raise
        except Exception as exc:
            # Transport errors: the class name only (their text could echo a URL or header).
            raise ExecutorError(f"databricks transport error ({type(exc).__name__})") from None
        if state != "SUCCEEDED":
            err = payload.get("status", {}).get("error", {})
            code = _safe_code(err.get("error_code")) if isinstance(err, dict) else "unspecified"  # pyright: ignore[reportUnknownMemberType]
            raise ExecutorError(f"databricks statement ended {state or 'UNKNOWN'} ({code})")
        result = payload.get("result", {}) or {}
        if result.get("next_chunk_internal_link"):
            raise ExecutorError("result is chunked; narrow the request")
        rows = tuple(tuple(r) for r in (result.get("data_array") or []))
        scanned = len(rows)
        if scanned > limits.max_rows_scanned:
            raise BudgetBreach("rows_scanned_budget_exceeded")
        return ExecutionOutcome(rows=rows, rows_scanned=scanned, cost_units=Decimal(0))


@asynccontextmanager
async def open_databricks_executor(
    *, host: str, warehouse_id: str, scope: str = DATABRICKS_SCOPE
) -> AsyncIterator[DatabricksStatementExecutor]:
    """The real client: httpx plus an Entra token from DefaultAzureCredential (lazy imports).

    No network at open time: the token and the first request happen on ``execute``."""
    import httpx
    from azure.identity.aio import DefaultAzureCredential

    credential = DefaultAzureCredential()

    async def token() -> str:
        return (await credential.get_token(scope)).token

    try:
        async with httpx.AsyncClient(
            base_url=f"https://{host}",
            timeout=httpx.Timeout(60.0),
            follow_redirects=False,
        ) as client:
            yield DatabricksStatementExecutor(client, token, warehouse_id=warehouse_id)
    finally:
        await credential.close()
