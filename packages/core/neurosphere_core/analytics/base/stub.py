"""Stub SQL endpoint: a stdlib ``sqlite3`` ``SqlExecutor`` for contract tests (PRP-11 item 1).

READ THIS FIRST. The stub proves CONTRACT CONFORMANCE ONLY: that a vendor ``Dialect`` plus the
shared renderer produce statements whose results match the fixture adapter within the
documented tolerance. It proves nothing about Fabric, Synapse or Databricks behaviour, SQL
dialect coverage, plans, limits or performance. There is no local emulator for those engines
(PRP-11 clarification 7); real behaviour is evidenced only by the operator-approved live gate.

How a vendor dialect runs on SQLite: a ``Shim`` is a declared bundle of ordered rewrite rules
(regex over the statement text, applied in order) and Python functions/aggregates registered
with SQLite (for example an emulated ``APPROX_PERCENTILE``). The stub lists every shim it
applied in ``applied_shims`` so each adapter test can record them as G12 emulator-parity gaps.
``standard_shims`` supplies the two every dialect needs (exact decimal money, nearest-rank
quantile). The stub always adds its own ``scan-counter`` shim, which counts rows actually
scanned and aborts the statement mid-flight when the rows or cost budget is exceeded.

Cancellation is real: the statement runs in a worker thread; cancelling the awaiting task (the
time budget) sets a flag, calls ``Connection.interrupt()`` and a progress handler aborts the
running statement before the cancellation propagates.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import sqlite3
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from math import ceil
from typing import Any, Final

from neurosphere_core.analytics.base.dialect import Statement
from neurosphere_core.analytics.base.enforcement import (
    BreachReason,
    BudgetBreach,
    ExecutionLimits,
    ExecutionOutcome,
)
from neurosphere_core.analytics.base.records import (
    ANALYTICS_TABLE,
    AnalyticsRecord,
    format_timestamp,
)

PROGRESS_INTERVAL: Final = 50  # SQLite VM instructions between cancellation checks
DEFAULT_COST_UNITS_PER_ROW: Final = Decimal("0.001")
_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

_COLUMNS = (
    ("event_id", "TEXT"),
    ("event_time", "TEXT"),
    ("cloud", "TEXT"),
    ("customer_id", "TEXT"),
    ("domain_id", "TEXT"),
    ("provider", "TEXT"),
    ("model", "TEXT"),
    ("span_kind", "TEXT"),
    ("outcome", "TEXT"),
    ("currency", "TEXT"),
    ("duration_ms", "INTEGER"),
    ("input_tokens", "INTEGER"),
    ("output_tokens", "INTEGER"),
    ("cost_amount", "TEXT"),  # decimal text; exact math comes from the decimal shim
)


@dataclass(frozen=True)
class RewriteRule:
    """``re.sub(pattern, replacement, sql)`` applied to the statement text, in order."""

    name: str
    pattern: str
    replacement: str


@dataclass(frozen=True)
class FunctionShim:
    name: str
    nargs: int
    func: Callable[..., Any]
    deterministic: bool = True


@dataclass(frozen=True)
class AggregateShim:
    name: str
    nargs: int
    factory: Callable[[], Any]  # class with step(*args) / finalize()


@dataclass(frozen=True)
class Shim:
    """One declared emulator-parity gap: what had to be faked to run this dialect on SQLite."""

    name: str
    description: str
    rules: tuple[RewriteRule, ...] = ()
    functions: tuple[FunctionShim, ...] = ()
    aggregates: tuple[AggregateShim, ...] = ()


class _Cancelled(Exception):  # noqa: N818 - internal signal, never leaves the stub
    pass


def _number(value: object) -> int | Decimal:
    if isinstance(value, int):
        return value
    return Decimal(str(value))


def _text(value: int | Decimal) -> object:
    return value if isinstance(value, int) else format(value, "f")


class _DecimalSum:
    def __init__(self) -> None:
        self.total: Decimal | None = None

    def step(self, value: object) -> None:
        if value is not None:
            self.total = (self.total or Decimal(0)) + Decimal(str(value))

    def finalize(self) -> str | None:
        return None if self.total is None else format(self.total, "f")


class _DecimalExtreme:
    pick: Callable[[Decimal, Decimal], Decimal]

    def __init__(self) -> None:
        self.best: Decimal | None = None

    def step(self, value: object) -> None:
        if value is not None:
            current = Decimal(str(value))
            self.best = current if self.best is None else type(self).pick(self.best, current)

    def finalize(self) -> str | None:
        return None if self.best is None else format(self.best, "f")


class _DecimalMin(_DecimalExtreme):
    pick = staticmethod(min)


class _DecimalMax(_DecimalExtreme):
    pick = staticmethod(max)


class NearestRankQuantile:
    """Exact nearest-rank quantile (the fixture's definition) emulating an engine's approximate
    quantile function. Nulls are skipped; all-null gives NULL (unknown)."""

    def __init__(self) -> None:
        self.values: list[int | Decimal] = []
        self.q: Decimal | None = None

    def step(self, value: object, q: object) -> None:
        self.q = Decimal(str(q))
        if value is not None:
            self.values.append(_number(value))

    def finalize(self) -> object:
        if not self.values or self.q is None:
            return None
        ordered = sorted(self.values)
        index = max(ceil(self.q * len(ordered)), 1) - 1
        return _text(ordered[index])


def decimal_cost_shim() -> Shim:
    return Shim(
        name="decimal-cost",
        description=(
            "cost_amount is stored as decimal text; SUM/MIN/MAX over it are rewritten to "
            "exact Decimal aggregates (a real engine uses DECIMAL(38,12) natively)"
        ),
        rules=(
            RewriteRule(
                "decimal-cost-aggregates",
                r'\b(SUM|MIN|MAX)\(("cost_amount")\)',
                r"NS_DEC_\1(\2)",
            ),
        ),
        aggregates=(
            AggregateShim("NS_DEC_SUM", 1, _DecimalSum),
            AggregateShim("NS_DEC_MIN", 1, _DecimalMin),
            AggregateShim("NS_DEC_MAX", 1, _DecimalMax),
        ),
    )


def quantile_shim(function_name: str) -> Shim:
    return Shim(
        name=f"quantile-{function_name.lower()}",
        description=(
            f"{function_name}(col, q) emulated as an EXACT nearest-rank quantile; a real "
            "engine is approximate (t-digest/KLL) so the tolerance helper covers the gap"
        ),
        aggregates=(AggregateShim(function_name, 2, NearestRankQuantile),),
    )


def standard_shims(quantile_function: str = "PERCENTILE_APPROX") -> tuple[Shim, ...]:
    """The shims every dialect needs on SQLite. Add dialect-specific ones after these."""
    return (decimal_cost_shim(), quantile_shim(quantile_function))


class StubSqlEndpoint:
    """SQLite-backed ``SqlExecutor`` over the fixed analytics table. See the module docstring:
    contract conformance only, never vendor behaviour. Full-scan by construction (no indexes),
    so ``rows_scanned`` is the number of table rows the statement read."""

    def __init__(
        self,
        records: Sequence[AnalyticsRecord],
        *,
        shims: Sequence[Shim] = (),
        cost_units_per_row: Decimal = DEFAULT_COST_UNITS_PER_ROW,
        schema: str | None = None,
    ) -> None:
        if schema is not None and not _SCHEMA_RE.match(schema):
            raise ValueError("schema must be a plain identifier")
        self._shims = tuple(shims)
        self._cost_per_row = cost_units_per_row
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._ticks = 0
        self._limits: ExecutionLimits | None = None
        self._breach: BreachReason | None = None
        self.last_sql: str | None = None
        self.last_rows_processed = 0
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        qualified = f'"{ANALYTICS_TABLE}"'
        if schema is not None:
            self._conn.execute(f"ATTACH DATABASE ':memory:' AS \"{schema}\"")
            qualified = f'"{schema}".{qualified}'
        self._load(qualified, records)
        self._conn.execute("PRAGMA query_only = ON")
        self._conn.create_function("NS_TICK", 0, self._tick)
        for shim in self._shims:
            for fn in shim.functions:
                self._conn.create_function(
                    fn.name, fn.nargs, fn.func, deterministic=fn.deterministic
                )
            for agg in shim.aggregates:
                self._conn.create_aggregate(agg.name, agg.nargs, agg.factory)
        self._conn.set_progress_handler(self._progress, PROGRESS_INTERVAL)

    @property
    def applied_shims(self) -> tuple[tuple[str, str], ...]:
        """(name, description) of every shim in effect: record each as a G12 parity gap."""
        scan = (
            "scan-counter",
            "rows scanned counted by a per-row SQLite function; no engine stats",
        )
        return (*((s.name, s.description) for s in self._shims), scan)

    @property
    def row_count(self) -> int:
        return self._table_rows

    def _load(self, qualified: str, records: Sequence[AnalyticsRecord]) -> None:
        columns = ", ".join(f'"{name}" {kind}' for name, kind in _COLUMNS)
        self._conn.execute(f"CREATE TABLE {qualified} ({columns})")
        marks = ", ".join("?" for _ in _COLUMNS)
        self._conn.executemany(
            f"INSERT INTO {qualified} VALUES ({marks})",  # noqa: S608
            [
                (
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
                for r in records
            ],
        )
        self._conn.commit()
        self._table_rows = len(records)

    # --- statement preparation -------------------------------------------------------------

    def rewrite(self, sql: str) -> str:
        for shim in self._shims:
            for rule in shim.rules:
                sql = re.sub(rule.pattern, rule.replacement, sql)
        # Scan counter last: wrap the (possibly schema-qualified) table read.
        pattern = rf'FROM\s+((?:"[^"]+"\.)?"{ANALYTICS_TABLE}")'
        wrapped, n = re.subn(
            pattern, r'FROM (SELECT * FROM \1 WHERE NS_TICK()) AS "t"', sql, count=1
        )
        if n != 1:
            raise ValueError("statement does not read the analytics table")
        return wrapped

    # --- in-thread callbacks ---------------------------------------------------------------

    def _tick(self) -> int:
        if self._cancel.is_set():
            raise sqlite3.OperationalError("cancelled")
        self._ticks += 1
        limits = self._limits
        if limits is not None:
            if self._ticks > limits.max_rows_scanned:
                self._breach = "rows_scanned_budget_exceeded"
                raise sqlite3.OperationalError("rows budget")
            if self._cost_per_row * self._ticks > limits.max_cost_units:
                self._breach = "cost_budget_exceeded"
                raise sqlite3.OperationalError("cost budget")
        return 1

    def _progress(self) -> int:
        return 1 if self._cancel.is_set() else 0

    def _run(
        self, statement: Statement, limits: ExecutionLimits, cancel: threading.Event
    ) -> ExecutionOutcome:
        with self._lock:
            self._cancel = cancel
            if cancel.is_set():
                raise _Cancelled
            sql = statement.sql.lstrip()
            if not sql.upper().startswith("SELECT"):
                raise ValueError("the stub runs SELECT statements only")
            self._ticks = 0
            self._breach = None
            self._limits = limits
            self.last_sql = self.rewrite(sql)
            try:
                rows = self._conn.execute(self.last_sql, statement.params).fetchall()
            except sqlite3.OperationalError:
                if self._breach is not None:
                    raise BudgetBreach(self._breach) from None
                if cancel.is_set():
                    raise _Cancelled from None
                raise
            finally:
                self.last_rows_processed = self._ticks
                self._limits = None
            return ExecutionOutcome(
                rows=tuple(tuple(r) for r in rows),
                rows_scanned=self._ticks,
                cost_units=self._cost_per_row * self._ticks,
            )

    # --- SqlExecutor -----------------------------------------------------------------------

    async def execute(self, statement: Statement, *, limits: ExecutionLimits) -> ExecutionOutcome:
        cancel = threading.Event()
        task = asyncio.ensure_future(asyncio.to_thread(self._run, statement, limits, cancel))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            cancel.set()
            self._conn.interrupt()
            with contextlib.suppress(BaseException):
                await task  # the worker thread must have stopped before we return
            raise
