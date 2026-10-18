"""Versioned, idempotent T-SQL migrations for the Fabric analytics table (PRP-11 clarification 8).

Adapter-local: PRP-13 later generalises the runner. Rules every migration follows:

* named ``V<nnn>__<name>`` with strictly increasing, contiguous versions starting at 1;
* backward compatible and additive (create-if-missing, add nullable columns; never drop or
  rename), so an older adapter keeps working against a newer schema;
* idempotent: each statement is guarded (``IF OBJECT_ID(...) IS NULL CREATE TABLE ...``), so a
  half-applied run can be repeated; the ledger table additionally records what ran and a
  checksum, so editing an applied migration is detected instead of silently ignored;
* Fabric Data Warehouse types only (``varchar``, ``bigint``, ``datetime2(6)``,
  ``decimal(38,12)``); no ``nvarchar``, no enforced constraints or indexes. Support for each
  construct in Fabric DW is unverified here (Learn MCP unreachable), a G12/G01 gap.

A ``lakehouse_sql_endpoint`` item is read-only: ``apply_migrations`` refuses it before any
statement runs. ``MigrationExecutor`` is deliberately separate from the read-only
``SqlExecutor`` that serves analytics queries, so a query path can never run DDL.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol

from neurosphere_core.analytics.base.records import ANALYTICS_TABLE, format_timestamp
from neurosphere_core.analytics.fabric.config import FabricConfig
from neurosphere_core.errors import CapabilityUnavailableError

LEDGER_TABLE: Final = "ns_schema_migrations"
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class MigrationExecutor(Protocol):
    """Runs write statements for migrations. Never used for analytics queries."""

    async def run(self, sql: str, params: tuple[object, ...] = ()) -> None: ...

    async def query(
        self, sql: str, params: tuple[object, ...] = ()
    ) -> list[tuple[object, ...]]: ...


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]  # contain ``{schema}`` (already a bracket-quoted identifier)

    @property
    def id(self) -> str:
        return f"V{self.version:03d}__{self.name}"

    def render(self, schema: str) -> tuple[str, ...]:
        quoted = "[" + schema.replace("]", "]]") + "]"
        return tuple(s.replace("{schema}", quoted) for s in self.statements)

    def checksum(self, schema: str) -> str:
        return hashlib.sha256("\n".join(self.render(schema)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MigrationReport:
    applied: tuple[str, ...]
    already_applied: tuple[str, ...]


_LEDGER_DDL = (
    f"IF OBJECT_ID(N'{{schema}}.[{LEDGER_TABLE}]', N'U') IS NULL "
    f"CREATE TABLE {{schema}}.[{LEDGER_TABLE}] ("
    "[version] int NOT NULL, [name] varchar(128) NOT NULL, [checksum] varchar(64) NOT NULL, "
    "[applied_at] datetime2(6) NOT NULL)"
)
_EVENTS_DDL = (
    f"IF OBJECT_ID(N'{{schema}}.[{ANALYTICS_TABLE}]', N'U') IS NULL "
    f"CREATE TABLE {{schema}}.[{ANALYTICS_TABLE}] ("
    "[event_id] varchar(256) NOT NULL, [event_time] datetime2(6) NOT NULL, "
    "[cloud] varchar(16) NOT NULL, [customer_id] varchar(128) NOT NULL, "
    "[domain_id] varchar(256) NULL, [provider] varchar(128) NULL, [model] varchar(256) NULL, "
    "[span_kind] varchar(64) NULL, [outcome] varchar(64) NULL, [currency] varchar(8) NULL, "
    "[duration_ms] bigint NULL, [input_tokens] bigint NULL, [output_tokens] bigint NULL, "
    "[cost_amount] decimal(38,12) NULL)"
)

MIGRATIONS: Final[tuple[Migration, ...]] = (
    Migration(1, "schema_ledger", (_LEDGER_DDL,)),
    Migration(2, "analytics_events", (_EVENTS_DDL,)),
)


def validate_migration_set(migrations: Sequence[Migration]) -> None:
    """Versions strictly increasing and contiguous from 1; names well formed; no empty set."""
    if not migrations:
        raise ValueError("no migrations")
    for expected, migration in enumerate(migrations, start=1):
        if migration.version != expected:
            raise ValueError(f"migration versions must be contiguous from 1 (got {migration.id})")
        if not _NAME_RE.match(migration.name) or not migration.statements:
            raise ValueError(f"malformed migration {migration.id}")


async def apply_migrations(
    executor: MigrationExecutor,
    *,
    config: FabricConfig,
    migrations: Sequence[Migration] = MIGRATIONS,
    now: datetime | None = None,
) -> MigrationReport:
    """Apply pending migrations in order. Running it again applies nothing."""
    if config.read_only:
        raise CapabilityUnavailableError(
            "fabric_item_read_only",
            f"item kind {config.item_kind} is read-only; migrations need a warehouse",
        )
    validate_migration_set(migrations)
    schema = config.schema_name
    ledger = f"[{schema}].[{LEDGER_TABLE}]"
    # Bootstrap: the ledger table itself is migration 1 and is idempotent, so create it first.
    for statement in migrations[0].render(schema):
        await executor.run(statement)
    rows = await executor.query(f"SELECT [version], [checksum] FROM {ledger}")  # noqa: S608
    recorded = {int(str(r[0])): str(r[1]) for r in rows}
    stamp = format_timestamp(now or datetime.now(UTC))
    applied: list[str] = []
    already: list[str] = []
    for migration in migrations:
        checksum = migration.checksum(schema)
        if migration.version in recorded:
            if recorded[migration.version] != checksum:
                raise CapabilityUnavailableError(
                    "migration_checksum_mismatch",
                    f"applied migration {migration.id} was edited after it ran",
                )
            already.append(migration.id)
            continue
        if migration.version != 1:
            for statement in migration.render(schema):
                await executor.run(statement)
        await executor.run(
            f"INSERT INTO {ledger} ([version], [name], [checksum], [applied_at]) "  # noqa: S608
            "VALUES (?, ?, ?, ?)",
            (migration.version, migration.name, checksum, stamp),
        )
        applied.append(migration.id)
    return MigrationReport(applied=tuple(applied), already_applied=tuple(already))


__all__ = [
    "LEDGER_TABLE",
    "MIGRATIONS",
    "Migration",
    "MigrationExecutor",
    "MigrationReport",
    "apply_migrations",
    "validate_migration_set",
]
