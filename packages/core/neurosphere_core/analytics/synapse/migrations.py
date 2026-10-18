"""Versioned, backward-compatible, idempotent Synapse migrations plus a schema-version ledger.

PRP-13 generalises migrations later; this runner is adapter-local and deliberately small.

Rules every migration follows: file-style id ``V###__name``; additive only (never drop or
retype a column an older adapter reads); every statement is guarded (``IF OBJECT_ID(...) IS
NULL`` or ``CREATE OR ALTER``) so a crash between a statement and its ledger row is repaired
by simply re-running; the ledger stores a checksum and an edited, already-applied migration
raises ``MigrationError`` instead of silently diverging.

Mode differences (observed 2026-10-18; see ``dialect.py`` for the verification caveat):

* ``dedicated`` holds real tables. The events table is ``DISTRIBUTION = ROUND_ROBIN`` with a
  clustered columnstore index: telemetry is append-only, so even placement avoids skew and
  there is no stable hash key that matches every GROUP BY the contract allows (hash columns also
  cannot be updated and NULLs would pile onto one distribution). V002 adds statistics on the
  two columns every query filters or groups by. The ledger is a small ``REPLICATE`` table.
* ``serverless`` cannot hold regular tables (no distributed storage of its own). The events
  "table" is a view (``CREATE OR ALTER VIEW``) over ``OPENROWSET`` Parquet in the data lake,
  through an operator-created external data source named by ``external_data_source`` (its
  credential, a managed identity, is created by the operator, never here). The ledger is also
  a view that is regenerated with the full applied set on each record, because no table can
  hold it. String columns use a UTF-8 BIN2 collation, which Parquet strings need on serverless.

Executing DDL needs a driver connection the operator injects (``MigrationExecutor``); this
module never opens one.
"""

# ruff: noqa: S608 - identifiers are pattern-validated config or code constants; values are bound
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol

from neurosphere_core.analytics.base.records import ANALYTICS_TABLE, format_timestamp
from neurosphere_core.analytics.synapse.config import SynapseConfig

LEDGER_TABLE: Final = "ns_schema_version"
_UTF8 = "COLLATE Latin1_General_100_BIN2_UTF8"

# (name, dedicated type, serverless OPENROWSET type)
_COLUMNS: Final[tuple[tuple[str, str, str], ...]] = (
    ("event_id", "NVARCHAR(256) NOT NULL", f"VARCHAR(256) {_UTF8}"),
    ("event_time", "DATETIME2(6) NOT NULL", "DATETIME2(6)"),
    ("cloud", "NVARCHAR(16) NOT NULL", f"VARCHAR(16) {_UTF8}"),
    ("customer_id", "NVARCHAR(128) NOT NULL", f"VARCHAR(128) {_UTF8}"),
    ("domain_id", "NVARCHAR(256) NULL", f"VARCHAR(256) {_UTF8}"),
    ("provider", "NVARCHAR(128) NULL", f"VARCHAR(128) {_UTF8}"),
    ("model", "NVARCHAR(256) NULL", f"VARCHAR(256) {_UTF8}"),
    ("span_kind", "NVARCHAR(64) NULL", f"VARCHAR(64) {_UTF8}"),
    ("outcome", "NVARCHAR(64) NULL", f"VARCHAR(64) {_UTF8}"),
    ("currency", "NVARCHAR(16) NULL", f"VARCHAR(16) {_UTF8}"),
    ("duration_ms", "BIGINT NULL", "BIGINT"),
    ("input_tokens", "BIGINT NULL", "BIGINT"),
    ("output_tokens", "BIGINT NULL", "BIGINT"),
    ("cost_amount", "DECIMAL(38,12) NULL", "DECIMAL(38,12)"),
)


class MigrationError(Exception):
    """A migration cannot be applied or the ledger disagrees with the code."""


class MigrationExecutor(Protocol):
    """Runs one T-SQL statement in autocommit mode and returns any result rows. Injected."""

    async def run(
        self, sql: str, params: tuple[object, ...] = ()
    ) -> Sequence[Sequence[object]]: ...


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]

    @property
    def id(self) -> str:
        return f"V{self.version:03d}__{self.name}"

    @property
    def checksum(self) -> str:
        return hashlib.sha256("\n".join(self.statements).encode("utf-8")).hexdigest()


def _qualified(schema: str, name: str) -> str:
    return f"[{schema}].[{name}]"


def _lit(text: str) -> str:
    return "N'" + text.replace("'", "''") + "'"


def _dedicated(config: SynapseConfig) -> tuple[Migration, ...]:
    events = _qualified(config.schema_name, ANALYTICS_TABLE)
    columns = ", ".join(f"[{name}] {dedicated}" for name, dedicated, _ in _COLUMNS)
    create = (
        f"IF OBJECT_ID({_lit(events)}, N'U') IS NULL CREATE TABLE {events} ({columns}) "
        "WITH (DISTRIBUTION = ROUND_ROBIN, CLUSTERED COLUMNSTORE INDEX)"
    )
    stats = tuple(
        f"IF NOT EXISTS (SELECT 1 FROM sys.stats WHERE name = {_lit(stat)} "
        f"AND object_id = OBJECT_ID({_lit(events)})) "
        f"CREATE STATISTICS [{stat}] ON {events} ([{column}])"
        for stat, column in (
            ("ns_stat_events_time", "event_time"),
            ("ns_stat_events_domain", "domain_id"),
        )
    )
    return (
        Migration(1, "analytics_events_table", (create,)),
        Migration(2, "analytics_events_statistics", stats),
    )


def _serverless(config: SynapseConfig) -> tuple[Migration, ...]:
    if config.external_data_source is None:
        raise MigrationError("serverless migrations need external_data_source (the lake source)")
    events = _qualified(config.schema_name, ANALYTICS_TABLE)
    names = ", ".join(f"[{name}]" for name, _, _ in _COLUMNS)
    with_clause = ", ".join(f"[{name}] {serverless}" for name, _, serverless in _COLUMNS)
    view = (
        f"CREATE OR ALTER VIEW {events} AS SELECT {names} FROM OPENROWSET("
        f"BULK '{ANALYTICS_TABLE}/**', DATA_SOURCE = '{config.external_data_source}', "
        f"FORMAT = 'PARQUET') WITH ({with_clause}) AS [r]"
    )
    return (Migration(1, "analytics_events_view", (view,)),)


def migrations_for(config: SynapseConfig) -> tuple[Migration, ...]:
    found = _dedicated(config) if config.mode == "dedicated" else _serverless(config)
    if [m.version for m in found] != list(range(1, len(found) + 1)):
        raise MigrationError("migration versions must be contiguous from 1")  # pragma: no cover
    return found


# --- ledger ---------------------------------------------------------------------------------


def _ledger_view(schema: str, applied: Sequence[tuple[int, str, str]]) -> str:
    target = _qualified(schema, LEDGER_TABLE)
    if not applied:
        select = (
            "SELECT CAST(NULL AS INT) AS [version], CAST(NULL AS NVARCHAR(128)) AS [name], "
            "CAST(NULL AS CHAR(64)) AS [checksum] WHERE 1 = 0"
        )
    else:
        select = " UNION ALL ".join(
            f"SELECT CAST({v} AS INT) AS [version], CAST({_lit(n)} AS NVARCHAR(128)) AS [name], "
            f"CAST({_lit(c)} AS CHAR(64)) AS [checksum]"
            for v, n, c in applied
        )
    return f"CREATE OR ALTER VIEW {target} AS {select}"


async def _ledger_exists(executor: MigrationExecutor, schema: str) -> bool:
    rows = await executor.run(
        "SELECT COUNT(*) FROM sys.objects o JOIN sys.schemas s ON s.schema_id = o.schema_id "
        f"WHERE s.name = {_lit(schema)} AND o.name = {_lit(LEDGER_TABLE)}"
    )
    return bool(rows) and int(str(rows[0][0])) > 0


async def _read_ledger(executor: MigrationExecutor, schema: str) -> list[tuple[int, str, str]]:
    rows = await executor.run(
        f"SELECT [version], [name], [checksum] FROM {_qualified(schema, LEDGER_TABLE)}"
    )
    return sorted((int(str(r[0])), str(r[1]), str(r[2]).strip()) for r in rows)


async def apply_migrations(
    executor: MigrationExecutor, config: SynapseConfig, *, now: datetime | None = None
) -> tuple[str, ...]:
    """Apply pending migrations in order and return the ids applied by THIS call (empty when the
    schema is current). Safe to re-run. Raises ``MigrationError`` on checksum drift."""
    migrations = migrations_for(config)
    schema = config.schema_name
    await executor.run(
        f"IF SCHEMA_ID({_lit(schema)}) IS NULL EXEC({_lit('CREATE SCHEMA [' + schema + ']')})"
    )
    ledger = _qualified(schema, LEDGER_TABLE)
    if not await _ledger_exists(executor, schema):
        if config.mode == "dedicated":
            await executor.run(
                f"IF OBJECT_ID({_lit(ledger)}, N'U') IS NULL CREATE TABLE {ledger} "
                "([version] INT NOT NULL, [name] NVARCHAR(128) NOT NULL, "
                "[checksum] CHAR(64) NOT NULL, [applied_at] DATETIME2(0) NOT NULL) "
                "WITH (DISTRIBUTION = REPLICATE, CLUSTERED COLUMNSTORE INDEX)"
            )
        else:
            await executor.run(_ledger_view(schema, ()))
    applied = await _read_ledger(executor, schema)
    known = {m.version: m for m in migrations}
    for version, name, checksum in applied:
        migration = known.get(version)
        if migration is None:
            raise MigrationError(f"ledger has V{version:03d}, which this adapter does not know")
        if migration.name != name or migration.checksum != checksum:
            raise MigrationError(f"{migration.id} was applied with different content (drift)")
    done = {v for v, _, _ in applied}
    stamp = format_timestamp(now or datetime.now(UTC))[:19]
    ran: list[str] = []
    for migration in migrations:
        if migration.version in done:
            continue
        for statement in migration.statements:
            await executor.run(statement)
        entry = (migration.version, migration.name, migration.checksum)
        if config.mode == "dedicated":
            await executor.run(
                f"INSERT INTO {ledger} ([version], [name], [checksum], [applied_at]) "
                "VALUES (?, ?, ?, ?)",
                (*entry, stamp),
            )
        else:
            applied = sorted([*applied, entry])
            await executor.run(_ledger_view(schema, applied))
        ran.append(migration.id)
    return tuple(ran)
