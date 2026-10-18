"""G01 live run (analytics adapters): the equivalence workload against real Commercial backends.

Operator-approved only. Refuses unless NS_LIVE_APPROVED=1 (checked first, before argument parsing,
any import of project code, azure or httpx, or any network access).

What it does, per adapter named with ``--adapter`` (each is independent: one adapter's FAIL or
OPEN never stops or colours another): creates a run-scoped schema, applies the adapter's
migrations, loads the SYNTHETIC fixture dataset (``build_dataset("commercial")``, never production
data), runs the same request set as ``tests/integration/analytics/test_equivalence.py`` through
the live adapter, compares live vs fixture with ``compare_results`` (counts and sums exact,
quantiles within the documented tolerance), runs the same requests through the SQLite stub
endpoint to record the live-vs-stub delta and the stub's applied shims (G12), then drops the run
schema unless ``--keep``. Every request carries a budget (timeout, rows, cost).

Backends:
  databricks  real executor in this script: ``httpx`` against the Azure Databricks SQL Statement
              Execution API with named parameters; Entra token from ``DefaultAzureCredential``.
  fabric      OPEN. Fabric SQL endpoints speak TDS and no TDS driver is approved (it would need an
  synapse     ADR-0002 stack-pin row and operator approval for mssql-python or ODBC Driver 18).
              Recorded OPEN with that reason; no connection is attempted.

Environment (names only; values are never printed or written):
  NS_LIVE_APPROVED=1                       required approval gate
  NS_G01A_OPERATOR                         operator name (or --operator)
  NS_G01A_DATABRICKS_HOST                  adb-<id>.<n>.azuredatabricks.net (Commercial only)
  NS_G01A_DATABRICKS_WAREHOUSE_ID          SQL warehouse id (16 hex)
  NS_G01A_DATABRICKS_CATALOG               existing Unity Catalog catalog for the run schema
  NS_G01A_DATABRICKS_REGION                e.g. eastus2
  NS_G01A_DATABRICKS_SKU_CLASS             optional label, e.g. serverless-2X-Small
  NS_G01A_SYNAPSE_WORKSPACE / _DATABASE / _MODE (serverless|dedicated) / _HOST / _REGION /
  NS_G01A_SYNAPSE_SKU_CLASS                optional; validated by SynapseConfig when supplied
  NS_G01A_FABRIC_HOST / _DATABASE / _REGION / NS_G01A_FABRIC_SKU_CLASS
                                           optional; validated by FabricConfig when supplied

Auth is Entra only (DefaultAzureCredential / managed identity). No key, token, PAT or password is
accepted from arguments or environment.

Commercial only: a Government cloud, region or host is refused (exit 2). No Government
subscription exists; Government stays OPEN for G01/G02. Availability is not authorization and
nothing here is an ATO or FedRAMP claim.

Exit codes: 0 every attempted adapter PASS; 1 any FAIL (checked first); 2 REFUSED (approval,
interpreter, arguments, cloud or config precondition; nothing was run); 3 no FAIL but at least one
adapter OPEN (not run, so not evidence).

Evidence: docs/evidence/G01/analytics/<UTC date>-<adapter>-commercial.{json,md}, built from
whitelisted fields only and passed through a secret scrubber that fails the run if anything looks
like a credential.

Databricks API shape (docs: https://learn.microsoft.com/azure/databricks/dev-tools/sql-execution-tutorial
and https://learn.microsoft.com/azure/databricks/dev-tools/auth/ ; the Entra resource id
2ff814a6-3304-4ab8-85cb-cd0e6f879c1d is the Azure Databricks application, scope
``<id>/.default``, the same across Azure environments: verified on Learn 2026-10-18,
https://learn.microsoft.com/azure/databricks/dev-tools/auth/aad-token-manual). The Statement
Execution API request/response shape and its limits are not verified; the live run verifies them.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib
import json
import os
import re
import sys
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]

REPO = Path(__file__).resolve().parents[2]
SCRIPT_VERSION = "1.0.0"
GATE = "G01"
ADAPTERS = ("fabric", "synapse", "databricks")
EVIDENCE_DIR = REPO / "docs" / "evidence" / "G01" / "analytics"
DATA_LABEL = (
    "synthetic sandbox dataset (build_dataset('commercial')); no production or customer data"
)
NOT_A_CLAIM = (
    "Commercial integration evidence for one backend SKU class and region only. Availability is "
    "not authorization; this is not an ATO, FedRAMP or compliance claim. Government stays OPEN."
)
DRIVER_REASON = (
    "no approved TDS driver: Fabric and Synapse SQL endpoints speak TDS and the live executor "
    "needs mssql-python or ODBC Driver 18, which requires an ADR-0002 stack-pin row and "
    "operator approval. No connection was attempted."
)
# Azure Databricks Entra application (resource) id; verified on Learn 2026-10-18 (aad-token-manual).
DATABRICKS_RESOURCE_ID = "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d"
DATABRICKS_SCOPE = f"{DATABRICKS_RESOURCE_ID}/.default"
STATEMENTS_PATH = "/api/2.0/sql/statements"
MAX_PARAMETERS = 256  # Statement Execution API limit on parameters per statement (unverified)
INSERT_BATCH_ROWS = 15  # 14 columns x 15 rows = 210 parameters, under the limit
DEFAULT_TIMEOUT_MS = 30_000  # the Budget contract ceiling; covers warehouse cold start

_GOV_REGION_PREFIXES = ("usgov", "usdod")
_GOV_HOST_MARKERS = (
    ".azure.us",
    "usgovcloudapi",
    ".fabric.microsoft.us",
    ".databricks.azure.us",
    "microsoft.us",
)
_ENV_PREFIX = "NS_G01A_"

# (column, SQL type) in table order; the loader casts every bound value explicitly because the
# Statement Execution API types parameters from the declared type, not from the target column.
COLUMN_TYPES: tuple[tuple[str, str], ...] = (
    ("event_id", "STRING"),
    ("event_time", "TIMESTAMP"),
    ("cloud", "STRING"),
    ("customer_id", "STRING"),
    ("domain_id", "STRING"),
    ("provider", "STRING"),
    ("model", "STRING"),
    ("span_kind", "STRING"),
    ("outcome", "STRING"),
    ("currency", "STRING"),
    ("duration_ms", "BIGINT"),
    ("input_tokens", "BIGINT"),
    ("output_tokens", "BIGINT"),
    ("cost_amount", "DECIMAL(38,12)"),
)


class RefusedError(RuntimeError):
    """A precondition failed before anything ran."""


class ExecutorError(RuntimeError):
    """A live statement failed. The message never carries query text, values or credentials."""


# --------------------------------------------------------------------------- scrubber

_SECRET_VALUE_PATTERNS = (
    re.compile(r"eyJ[A-Za-z0-9_-]{8,}"),  # JWT header
    re.compile(r"AccountKey\s*=", re.IGNORECASE),
    re.compile(r"SharedAccessKey(Name)?\s*=", re.IGNORECASE),
    re.compile(r"DefaultEndpointsProtocol\s*=", re.IGNORECASE),
    re.compile(r"-----BEGIN"),
    re.compile(r"[A-Za-z0-9+/]{40,}={1,2}"),  # long base64 with padding
    re.compile(r"(?i)\b(password|passwd|secret|api[-_]?key|bearer)\b\s*[:=]\s*\S"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\bdapi[0-9a-f]{16,}"),  # Databricks personal access token
    re.compile(r"(?i)[?&]sig=[A-Za-z0-9%+/=]{8,}"),
)
_SECRET_KEY_PATTERN = re.compile(
    r"(?i)(access.?token|primary.?key|secondary.?key|connection.?string|list.?keys"
    r"|password|secret|sas.?token|api.?key|bearer|\bpat\b)"
)


class ScrubError(RuntimeError):
    pass


def _looks_secret(text: str) -> bool:
    return any(p.search(text) for p in _SECRET_VALUE_PATTERNS)


def scrub(value: Any, path: str = "$") -> None:
    """Raise ``ScrubError`` if any key or string value in ``value`` looks like a credential."""
    if isinstance(value, dict):
        for key, item in value.items():  # pyright: ignore[reportUnknownVariableType]
            k = str(key)  # pyright: ignore[reportUnknownArgumentType]
            if _SECRET_KEY_PATTERN.search(k) or _looks_secret(k):
                raise ScrubError(f"secret-like key at {path}.{k}")
            scrub(item, f"{path}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
            scrub(item, f"{path}[{i}]")
    elif isinstance(value, str) and _looks_secret(value):
        raise ScrubError(f"secret-like value at {path}")


def safe_text(text: str, limit: int = 200) -> str:
    """Truncate error text; redact it entirely if it matches a secret pattern."""
    cleaned = " ".join(text.split())[:limit]
    return "[redacted: matched a secret pattern]" if _looks_secret(cleaned) else cleaned


# --------------------------------------------------------------------------- data shapes


@dataclass(frozen=True)
class AdapterSettings:
    name: str
    region: str
    sku_class: str
    config: Mapping[str, str]  # validated plain strings; never written to evidence


@dataclass(frozen=True)
class RunOptions:
    operator: str
    keep: bool
    run_id: str
    timeout_ms: int = DEFAULT_TIMEOUT_MS


@dataclass
class AdapterResult:
    status: str  # PASS | FAIL | OPEN
    reason: str
    cases: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    stub_shims: list[dict[str, str]] = field(default_factory=list[dict[str, str]])
    teardown: dict[str, Any] = field(default_factory=dict[str, Any])
    caveats: list[str] = field(default_factory=list[str])
    run_schema: str | None = None
    elapsed_s: float = 0.0


AdapterRunner = Callable[[AdapterSettings, RunOptions], Awaitable[AdapterResult]]


# --------------------------------------------------------------------------- config / cloud


def _env_name(adapter: str, suffix: str) -> str:
    return f"{_ENV_PREFIX}{adapter.upper()}_{suffix}"


def _get(adapter: str, suffix: str) -> str:
    return os.environ.get(_env_name(adapter, suffix), "").strip()


def _pydantic_summary(exc: Exception) -> str:
    """Field names and our own static messages only; never the input (it may be a secret)."""
    getter: Any = getattr(exc, "errors", None)
    if getter is None:
        return safe_text(str(exc))
    entries: list[dict[str, Any]] = list(getter())
    parts: list[str] = []
    for e in entries:
        loc = ".".join(str(p) for p in e.get("loc", ())) or "config"
        parts.append(f"{loc}: {safe_text(str(e.get('msg', 'invalid')), 120)}")
    return "; ".join(parts)


def _refuse_if_government(adapter: str, region: str, hosts: Sequence[str]) -> None:
    if region.lower().startswith(_GOV_REGION_PREFIXES):
        raise RefusedError(
            f"{adapter}: region {region!r} is a Government region. This gate is Commercial only; "
            "Government stays OPEN for G01/G02 (no Government subscription)."
        )
    for host in hosts:
        low = host.lower()
        if any(marker in low for marker in _GOV_HOST_MARKERS):
            raise RefusedError(
                f"{adapter}: a configured host is a Government endpoint. This gate is Commercial "
                "only; Government stays OPEN for G01/G02 (no Government subscription)."
            )


def validate_adapter(adapter: str) -> AdapterSettings:
    """Read and validate one adapter's environment through its own config model."""
    region = _get(adapter, "REGION").lower()
    sku = _get(adapter, "SKU_CLASS") or "unspecified"
    host = _get(adapter, "HOST")
    _refuse_if_government(adapter, region, [host])
    config: dict[str, str] = {}

    def need(suffix: str) -> str:
        value = _get(adapter, suffix)
        if not value:
            raise RefusedError(f"{adapter}: set {_env_name(adapter, suffix)}. Nothing was run.")
        return value

    try:
        if adapter == "databricks":
            from neurosphere_core.analytics.databricks import DatabricksConfig

            config = {
                "host": need("HOST"),
                "warehouse_id": need("WAREHOUSE_ID"),
                "catalog": need("CATALOG"),
            }
            region = need("REGION").lower()
            _refuse_if_government(adapter, region, [config["host"]])
            DatabricksConfig.model_validate(
                {
                    "cloud": "commercial",
                    "region": region,
                    "workspace_host": config["host"],
                    "warehouse_id": config["warehouse_id"],
                    "catalog": config["catalog"],
                    "schema_name": "ns_g01a_validate",
                }
            )
        elif adapter == "fabric" and host:
            from neurosphere_core.analytics.fabric import FabricConfig

            database = need("DATABASE")
            region = need("REGION").lower()
            FabricConfig.model_validate(
                {
                    "cloud": "commercial",
                    "region": region,
                    "sql_endpoint_host": host,
                    "database": database,
                }
            )
            config = {"configured": "validated"}
        elif adapter == "synapse" and (_get(adapter, "WORKSPACE") or host):
            from neurosphere_core.analytics.synapse.config import SynapseConfig, resolve_endpoint

            region = need("REGION").lower()
            raw: dict[str, str] = {
                "mode": need("MODE"),
                "workspace": need("WORKSPACE"),
                "database": need("DATABASE"),
            }
            if host:
                raw["host"] = host
            resolve_endpoint(SynapseConfig.model_validate(raw), cloud="commercial", region=region)
            config = {"configured": "validated"}
    except RefusedError:
        raise
    except Exception as exc:  # config models raise pydantic or InvalidSchemaError
        raise RefusedError(
            f"{adapter}: configuration refused ({_pydantic_summary(exc)}). Nothing was run."
        ) from None
    return AdapterSettings(
        name=adapter, region=region or "unspecified", sku_class=sku, config=config
    )


# --------------------------------------------------------------------------- Databricks executor

TokenProvider = Callable[[], Awaitable[str]]


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
            code = str(data.get("error_code", "")) if isinstance(data, dict) else ""  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            code = code if re.fullmatch(r"[A-Z_]{1,64}", code) else "unspecified"
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
        from neurosphere_core.analytics.base import BudgetBreach, ExecutionOutcome

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
            code = str(err.get("error_code", "")) if isinstance(err, dict) else ""  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            code = code if re.fullmatch(r"[A-Z_]{1,64}", code) else "unspecified"
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
    settings: AdapterSettings,
) -> AsyncIterator[DatabricksStatementExecutor]:
    """The real client: httpx plus an Entra token from DefaultAzureCredential (lazy imports)."""
    import httpx
    from azure.identity.aio import DefaultAzureCredential

    credential = DefaultAzureCredential()

    async def token() -> str:
        return (await credential.get_token(DATABRICKS_SCOPE)).token

    try:
        async with httpx.AsyncClient(
            base_url=f"https://{settings.config['host']}",
            timeout=httpx.Timeout(60.0),
            follow_redirects=False,
        ) as client:
            yield DatabricksStatementExecutor(
                client, token, warehouse_id=settings.config["warehouse_id"]
            )
    finally:
        await credential.close()


# --------------------------------------------------------------------------- workload


def load_workload() -> Any:
    """The equivalence suite's cases and builders (imported lazily; synthetic data only)."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    support = importlib.import_module("tests.integration.analytics.support")
    equivalence = importlib.import_module("tests.integration.analytics.test_equivalence")
    return support, equivalence


def _q(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name):
        raise ValueError("identifier must be a plain name")
    return f"`{name}`"


def insert_statements(
    catalog: str, schema: str, records: Sequence[Any]
) -> list[tuple[str, tuple[object, ...]]]:
    """Batched multi-row INSERTs with an explicit CAST per bound value (values only as params)."""
    from neurosphere_core.analytics.base.records import ANALYTICS_TABLE, format_timestamp

    table = f"{_q(catalog)}.{_q(schema)}.{_q(ANALYTICS_TABLE)}"
    columns = ", ".join(_q(c) for c, _ in COLUMN_TYPES)
    out: list[tuple[str, tuple[object, ...]]] = []
    for start in range(0, len(records), INSERT_BATCH_ROWS):
        params: list[object] = []
        tuples: list[str] = []
        for r in records[start : start + INSERT_BATCH_ROWS]:
            row: tuple[object, ...] = (
                r.event_id,
                format_timestamp(r.event_time),
                r.cloud,
                r.customer_id,
                r.domain_id,
                r.provider,
                r.model,
                r.span_kind,
                r.outcome,
                r.currency,
                r.duration_ms,
                r.input_tokens,
                r.output_tokens,
                None if r.cost_amount is None else format(r.cost_amount, "f"),
            )
            marks: list[str] = []
            for value, (_, sql_type) in zip(row, COLUMN_TYPES, strict=True):
                params.append(value)
                marks.append(f"CAST(:p{len(params)} AS {sql_type})")
            tuples.append("(" + ", ".join(marks) + ")")
        out.append(
            (f"INSERT INTO {table} ({columns}) VALUES {', '.join(tuples)}", tuple(params))  # noqa: S608
        )
    return out


def _quantile_case(request: Any) -> bool:
    return str(request.aggregation.value) == "approx_quantile"


def _mismatch_texts(mismatches: Sequence[Any], left: str, right: str) -> list[str]:
    return [
        safe_text(f"{m.where}: {m.field} {left}={m.left} {right}={m.right}", 240)
        for m in mismatches[:5]
    ]


def tolerance_text() -> str:
    base = importlib.import_module("neurosphere_core.analytics.base")
    return (
        f"quantile rel<={base.QUANTILE_REL_TOL} abs<={base.QUANTILE_ABS_TOL}; "
        "counts, sums, min and max exact"
    )


async def run_cases(
    live: Any,
    stub: Any,
    fixture: Any,
    cases: Sequence[tuple[str, Any]],
    scope: Any,
    timeout_ms: int,
) -> list[dict[str, Any]]:
    from neurosphere_core.analytics.base import AnalyticsBudget, compare_results

    out: list[dict[str, Any]] = []
    for name, request in cases:
        budget = AnalyticsBudget(
            query=request.budget.query.model_copy(update={"timeout_ms": timeout_ms}),
            max_rows_scanned=request.budget.max_rows_scanned,
            max_cost_units=request.budget.max_cost_units,
        )
        request = request.model_copy(update={"budget": budget})
        record: dict[str, Any] = {
            "case": name,
            "kind": "approx_quantile" if _quantile_case(request) else "exact",
        }
        started = time.monotonic()
        try:
            expected = await fixture.aggregate(request, scope=scope)
            actual = await live.aggregate(request, scope=scope)
        except Exception as exc:
            record.update(
                status="FAIL",
                tolerance_result="not compared",
                error=f"{type(exc).__name__}: {safe_text(str(exc), 160)}",
            )
            out.append(record)
            continue
        record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        diff = compare_results(expected, actual)
        record["status"] = "PASS" if not diff else "FAIL"
        record["tolerance_result"] = (
            ("within quantile tolerance" if record["kind"] == "approx_quantile" else "exact match")
            if not diff
            else "mismatch"
        )
        record["mismatches"] = _mismatch_texts(diff, "fixture", "live")
        record["groups"] = len(actual.rows)
        record["live_rows_scanned_reported"] = int(actual.stats.rows_scanned)
        try:
            stub_result = await stub.aggregate(request, scope=scope)
            delta = compare_results(stub_result, actual)
            record["live_vs_stub"] = {
                "equivalent": not delta,
                "mismatch_count": len(delta),
                "mismatches": _mismatch_texts(delta, "stub", "live"),
            }
        except Exception as exc:
            record["live_vs_stub"] = {"error": f"{type(exc).__name__}"}
        out.append(record)
    return out


async def run_databricks(
    settings: AdapterSettings,
    options: RunOptions,
    *,
    executor: Any | None = None,
    stub_builder: Callable[[], Any] | None = None,
) -> AdapterResult:
    """Run the Databricks workload. ``executor`` is injected by tests; None builds the real one."""
    started = time.monotonic()
    if executor is None:
        async with open_databricks_executor(settings) as live_executor:
            result = await run_databricks(
                settings, options, executor=live_executor, stub_builder=stub_builder
            )
        result.elapsed_s = time.monotonic() - started
        return result

    from neurosphere_core.analytics.base import create_adapter
    from neurosphere_core.analytics.base.records import ANALYTICS_TABLE
    from neurosphere_core.analytics.databricks import DatabricksConfig
    from neurosphere_core.analytics.databricks.migrations import apply_migrations
    from neurosphere_core.analytics.fixture import build_dataset
    from neurosphere_core.errors import CapabilityUnavailableError

    support, equivalence = load_workload()
    schema = f"ns_g01a_{options.run_id}"
    catalog = settings.config["catalog"]
    config = DatabricksConfig.model_validate(
        {
            "cloud": "commercial",
            "region": settings.region,
            "workspace_host": settings.config["host"],
            "warehouse_id": settings.config["warehouse_id"],
            "catalog": catalog,
            "schema_name": schema,
        }
    )
    result = AdapterResult(status="FAIL", reason="not completed", run_schema=schema)
    result.caveats = [
        (
            "Statement Execution API reports no rows scanned or cost: rows_scanned is the "
            "returned row count and cost_units is 0, so the rows/cost budgets are weak on the "
            "live path (time budget and returned-row limit apply in full)."
        ),
        (
            "Statement Execution API shape and limits are unverified until this live run; the "
            "Entra resource id is verified on Learn (2026-10-18)."
        ),
    ]
    try:
        adapter = create_adapter(
            "databricks",
            cloud="commercial",
            region=settings.region,
            config=config.model_dump(mode="json"),
            executor=executor,
        )
    except CapabilityUnavailableError as exc:
        result.status = "OPEN"
        result.reason = f"capability matrix does not enable databricks here ({exc.code}); not run"
        result.run_schema = None
        return result

    built = (
        stub_builder()
        if stub_builder is not None
        else support.build_adapter("databricks", "commercial", settings.region)
    )
    scope = support.make_scope("commercial")
    fixture = support.fixture_adapter("commercial")
    cases = equivalence._cases("commercial")  # pyright: ignore[reportPrivateUsage]
    from neurosphere_core.analytics.base import ExecutionLimits

    limits = ExecutionLimits(max_rows_scanned=10_000_000, max_cost_units=Decimal(1_000_000))

    async def run_sql(sql: str, params: tuple[object, ...] = ()) -> None:
        from neurosphere_core.analytics.base import Statement

        await executor.execute(Statement(sql=sql, params=params), limits=limits)

    setup_ok = False
    try:
        await run_sql(f"CREATE SCHEMA IF NOT EXISTS {_q(catalog)}.{_q(schema)}")
        applied = await apply_migrations(executor, catalog=catalog, schema=schema)
        records = build_dataset("commercial")
        for sql, params in insert_statements(catalog, schema, records):
            await run_sql(sql, params)
        setup_ok = True
        result.caveats.append(
            f"schema created and migrations applied ({', '.join(applied) or 'none pending'}); "
            f"{len(records)} synthetic rows loaded into {ANALYTICS_TABLE}"
        )
        result.cases = await run_cases(
            adapter, built.adapter, fixture, cases, scope, options.timeout_ms
        )
        failed = [c for c in result.cases if c["status"] != "PASS"]
        result.status = "FAIL" if failed else "PASS"
        result.reason = (
            f"{len(failed)} of {len(result.cases)} cases failed" if failed else "all cases passed"
        )
    except Exception as exc:
        result.status = "FAIL"
        phase = "case run" if setup_ok else "setup"
        result.reason = f"{phase} failed: {type(exc).__name__}: {safe_text(str(exc), 160)}"
    finally:
        result.stub_shims = [
            {"name": name, "rule": rule} for name, rule in built.endpoint.applied_shims
        ]
        result.teardown = await _teardown(run_sql, catalog, schema, keep=options.keep)
        if result.teardown.get("status") == "FAILED" and result.status == "PASS":
            result.status = "FAIL"
            result.reason = "cases passed but teardown failed; the run schema may remain"
    result.elapsed_s = time.monotonic() - started
    return result


async def _teardown(
    run_sql: Callable[..., Awaitable[None]], catalog: str, schema: str, *, keep: bool
) -> dict[str, Any]:
    if keep:
        return {"status": "KEPT", "note": "--keep: run schema left in place for inspection"}
    try:
        await asyncio.shield(run_sql(f"DROP SCHEMA IF EXISTS {_q(catalog)}.{_q(schema)} CASCADE"))
    except Exception as exc:
        return {"status": "FAILED", "error": f"{type(exc).__name__}: {safe_text(str(exc), 160)}"}
    return {"status": "DROPPED"}


async def run_open_driver(settings: AdapterSettings, options: RunOptions) -> AdapterResult:
    """Fabric and Synapse: no approved TDS driver. Recorded OPEN; nothing is connected."""
    del options
    return AdapterResult(
        status="OPEN",
        reason=DRIVER_REASON,
        caveats=[
            "OPEN is not a skip and not a pass: no live evidence exists for this adapter.",
            "Stub equivalence tests are contract conformance only, never evidence that the "
            f"{settings.name} vendor works in a cloud/region.",
        ],
        teardown={"status": "NOT_APPLICABLE", "note": "nothing was created"},
    )


DEFAULT_RUNNERS: dict[str, AdapterRunner] = {
    "databricks": run_databricks,
    "fabric": run_open_driver,
    "synapse": run_open_driver,
}


# --------------------------------------------------------------------------- evidence


def _utcnow() -> datetime:
    return datetime.now(UTC)


def build_evidence(
    settings: AdapterSettings, options: RunOptions, result: AdapterResult, *, when: datetime
) -> dict[str, Any]:
    """Whitelisted fields only: nothing from the environment or the API is copied through."""
    attempted = result.status != "OPEN"
    return {
        "gate": GATE,
        "scope": "analytics adapter, Commercial only",
        "adapter": settings.name,
        "cloud": "commercial",
        "status": result.status,
        "reason": result.reason,
        "backend_sku_class": settings.sku_class,
        "region": settings.region,
        "date": when.strftime("%Y-%m-%d"),
        "run_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "operator": options.operator,
        "script_version": SCRIPT_VERSION,
        "data": DATA_LABEL,
        "claim_boundary": NOT_A_CLAIM,
        "tolerance": tolerance_text() if attempted else "not applicable (not run)",
        "budget_timeout_ms": options.timeout_ms if attempted else None,
        "run_schema": result.run_schema,
        "cases": result.cases,
        "stub_delta_g12": {
            "note": (
                "live vs stub per case is in cases[].live_vs_stub; the stub runs vendor SQL on "
                "SQLite through the declared shims below, so these are the G12 parity gaps"
            ),
            "applied_shims": result.stub_shims,
        },
        "teardown": result.teardown,
        "caveats": result.caveats,
        "elapsed_s": round(result.elapsed_s, 1),
    }


def render_markdown(evidence: Mapping[str, Any]) -> str:
    lines = [
        f"# G01 analytics evidence: {evidence['adapter']} (Commercial)",
        "",
        f"- Status: **{evidence['status']}**",
        f"- Reason: {evidence['reason']}",
        f"- Backend SKU class: {evidence['backend_sku_class']}",
        f"- Region: {evidence['region']}",
        f"- Date: {evidence['date']}",
        f"- Operator: {evidence['operator']}",
        f"- Data: {evidence['data']}",
        f"- Tolerance: {evidence['tolerance']}",
        f"- Teardown: {evidence['teardown'].get('status', 'n/a')}",
        f"- Boundary: {evidence['claim_boundary']}",
        "",
    ]
    cases = evidence["cases"]
    if cases:
        lines += [
            "## Cases",
            "",
            "| Case | Status | Tolerance result | Live vs stub |",
            "|---|---|---|---|",
        ]
        for c in cases:
            stub = c.get("live_vs_stub", {})
            delta = (
                "equivalent"
                if stub.get("equivalent")
                else f"{stub.get('mismatch_count', stub.get('error', 'n/a'))} mismatches"
            )
            lines.append(
                f"| {c['case']} | {c['status']} | {c.get('tolerance_result', '')} | {delta} |"
            )
        lines.append("")
    shims = evidence["stub_delta_g12"]["applied_shims"]
    if shims:
        lines += ["## Stub shims in effect (G12 parity gaps)", ""]
        lines += [f"- `{s['name']}`: {s['rule']}" for s in shims]
        lines.append("")
    if evidence["caveats"]:
        lines += ["## Caveats", ""] + [f"- {c}" for c in evidence["caveats"]] + [""]
    return "\n".join(lines)


def write_evidence(evidence: dict[str, Any], evidence_dir: Path) -> Path:
    """Scrub, then write. A ScrubError aborts before anything touches the disk."""
    scrub(evidence)
    markdown = render_markdown(evidence)
    scrub(markdown)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{evidence['date']}-{evidence['adapter']}-commercial"
    path = evidence_dir / f"{stem}.json"
    if path.exists():
        stamp = _utcnow().strftime("%H%M%S")
        path = evidence_dir / f"{evidence['date']}-{stamp}-{evidence['adapter']}-commercial.json"
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.with_suffix(".md").write_text(markdown, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- main


async def _await(awaitable: Awaitable[AdapterResult]) -> AdapterResult:
    return await awaitable


def exit_code(statuses: Sequence[str]) -> int:
    """Any FAIL -> 1; else any OPEN -> 3; else 0. (2 is reserved for REFUSED.)"""
    if "FAIL" in statuses:
        return 1
    if "OPEN" in statuses:
        return 3
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="G01 analytics live gate (Commercial only; Entra auth only; operator-approved)."
    )
    ap.add_argument(
        "--adapter",
        action="append",
        required=True,
        choices=ADAPTERS,
        help="adapter to run; repeat to run several (only the named adapters run)",
    )
    ap.add_argument("--operator", default=None, help="operator name for the evidence header")
    ap.add_argument("--keep", action="store_true", help="keep the run schema (default: drop it)")
    ap.add_argument(
        "--timeout-ms",
        type=int,
        default=DEFAULT_TIMEOUT_MS,
        help="per-request time budget in ms (contract ceiling 30000)",
    )
    ap.add_argument("--evidence-dir", default=str(EVIDENCE_DIR))
    return ap


def main(
    argv: Sequence[str] | None = None,
    *,
    runners: Mapping[str, AdapterRunner] | None = None,
) -> int:
    if os.environ.get("NS_LIVE_APPROVED") != "1":
        print(
            "REFUSED: g01_analytics_live.py runs against real Azure backends and needs operator "
            "approval; set NS_LIVE_APPROVED=1. No connection was attempted.",
            file=sys.stderr,
        )
        return 2
    try:
        importlib.import_module("neurosphere_core.analytics.base")
    except ImportError:
        print(
            "REFUSED: neurosphere_core is not importable; run with `uv run python "
            "scripts/gates/g01_analytics_live.py ...`. No connection was attempted.",
            file=sys.stderr,
        )
        return 2
    try:
        args = build_parser().parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    if not 1000 <= args.timeout_ms <= DEFAULT_TIMEOUT_MS:
        print("REFUSED: --timeout-ms must be between 1000 and 30000.", file=sys.stderr)
        return 2

    names = list(dict.fromkeys(args.adapter))
    try:
        settings = [validate_adapter(n) for n in names]  # validate ALL before running any
    except RefusedError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    operator = args.operator or os.environ.get("NS_G01A_OPERATOR") or "unspecified"
    if _looks_secret(operator):
        print("REFUSED: the operator label looks like a credential.", file=sys.stderr)
        return 2
    active = dict(DEFAULT_RUNNERS if runners is None else runners)
    evidence_dir = Path(args.evidence_dir)
    statuses: list[str] = []
    for s in settings:
        options = RunOptions(
            operator=operator,
            keep=bool(args.keep),
            run_id=uuid.uuid4().hex[:12],
            timeout_ms=int(args.timeout_ms),
        )
        try:
            result = asyncio.run(_await(active[s.name](s, options)))
        except Exception as exc:  # one adapter's crash never stops or colours another
            result = AdapterResult(
                status="FAIL", reason=f"runner crashed: {type(exc).__name__}: {safe_text(str(exc))}"
            )
        evidence = build_evidence(s, options, result, when=_utcnow())
        try:
            path = write_evidence(evidence, evidence_dir)
        except ScrubError as exc:
            print(f"FAIL: {s.name}: evidence not written ({exc}).", file=sys.stderr)
            statuses.append("FAIL")
            continue
        statuses.append(result.status)
        print(f"{s.name}: {result.status} - {result.reason}\n  wrote {path}")
    return exit_code(statuses)


if __name__ == "__main__":
    raise SystemExit(main())
