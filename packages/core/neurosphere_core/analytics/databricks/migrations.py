"""Versioned, idempotent Databricks SQL migrations and a small runner (PRP-11 item 4).

PRP-13 generalises migration tooling; this is the adapter-local minimum. Rules: every migration is
backward-compatible (additive only), every statement is idempotent on its own
(``CREATE TABLE IF NOT EXISTS ... USING DELTA``), and additive ``ALTER TABLE ... ADD COLUMNS`` is
guarded by the schema-version ledger (Databricks SQL has no portable ``IF NOT EXISTS`` for ADD
COLUMNS), so applying twice is a no-op. Identifiers come from validated config only.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from neurosphere_core.analytics.base.dialect import Statement
from neurosphere_core.analytics.base.enforcement import ExecutionLimits, SqlExecutor
from neurosphere_core.analytics.base.records import ANALYTICS_TABLE
from neurosphere_core.analytics.base.stub import RewriteRule

LEDGER_TABLE: Final = "ns_schema_version"
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_LIMITS: Final = ExecutionLimits(max_rows_scanned=1_000_000, max_cost_units=Decimal(1_000_000))


def _q(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError("identifier must be a plain name")
    return f"`{name}`"


def _fq(catalog: str, schema: str, table: str) -> str:
    return f"{_q(catalog)}.{_q(schema)}.{_q(table)}"


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    statements: Callable[[str, str], tuple[str, ...]]


def _v001(catalog: str, schema: str) -> tuple[str, ...]:
    table = _fq(catalog, schema, ANALYTICS_TABLE)
    return (
        f"CREATE TABLE IF NOT EXISTS {table} ("
        "event_id STRING, event_time TIMESTAMP, cloud STRING, customer_id STRING, "
        "domain_id STRING, provider STRING, model STRING, span_kind STRING, outcome STRING, "
        "currency STRING, duration_ms BIGINT, input_tokens BIGINT, output_tokens BIGINT, "
        "cost_amount DECIMAL(38,12)) USING DELTA",
    )


def _v002(catalog: str, schema: str) -> tuple[str, ...]:
    table = _fq(catalog, schema, ANALYTICS_TABLE)
    return (f"ALTER TABLE {table} ADD COLUMNS (trace_id STRING)",)


MIGRATIONS: Final[tuple[Migration, ...]] = (
    Migration("V001", "create_analytics_events", _v001),
    Migration("V002", "add_trace_id", _v002),
)

# How the statements above run on SQLite in tests (a declared G12 gap, applied in order).
SQLITE_MIGRATION_REWRITES: Final = (
    RewriteRule("drop-catalog", r"`[^`]+`\.(`[^`]+`\.`[^`]+`)", r"\1"),
    RewriteRule("backticks", r"`([^`]+)`", r'"\1"'),
    RewriteRule("using-delta", r"\s+USING DELTA", ""),
    RewriteRule("add-columns", r"ADD COLUMNS \((\w+) STRING\)", r"ADD COLUMN \1 TEXT"),
    RewriteRule("ledger-params", r":p\d+\b", "?"),
)


async def _run(
    executor: SqlExecutor, sql: str, params: tuple[object, ...] = ()
) -> tuple[tuple[object, ...], ...]:
    outcome = await executor.execute(Statement(sql=sql, params=params), limits=_LIMITS)
    return outcome.rows


async def apply_migrations(executor: SqlExecutor, *, catalog: str, schema: str) -> tuple[str, ...]:
    """Apply pending migrations in version order; return the versions applied this call."""
    ledger = _fq(catalog, schema, LEDGER_TABLE)
    await _run(
        executor,
        f"CREATE TABLE IF NOT EXISTS {ledger} (version STRING, name STRING) USING DELTA",
    )
    rows = await _run(executor, f"SELECT version FROM {ledger}")  # noqa: S608
    done = {str(r[0]) for r in rows}
    applied: list[str] = []
    for migration in sorted(MIGRATIONS, key=lambda m: m.version):
        if migration.version in done:
            continue
        for sql in migration.statements(catalog, schema):
            await _run(executor, sql)
        await _run(
            executor,
            f"INSERT INTO {ledger} VALUES (:p1, :p2)",  # noqa: S608
            (migration.version, migration.name),
        )
        applied.append(migration.version)
    return tuple(applied)
