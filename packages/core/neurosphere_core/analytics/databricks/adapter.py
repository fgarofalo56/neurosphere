"""Azure Databricks SQL warehouse adapter: ``SqlAnalytics`` + ``DatabricksDialect`` (PRP-11)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from pydantic import ValidationError

from neurosphere_core.analytics.base.enforcement import SqlExecutor
from neurosphere_core.analytics.base.sql_adapter import SqlAnalytics
from neurosphere_core.analytics.base.stub import (
    RewriteRule,
    Shim,
    standard_shims,
)
from neurosphere_core.analytics.databricks.config import DatabricksConfig
from neurosphere_core.analytics.databricks.dialect import DatabricksDialect
from neurosphere_core.errors import InvalidSchemaError

BACKEND: Final = "databricks"

# What the sqlite stub cannot reproduce. Each entry is evidence the live gate (G12) still owes.
G12_PARITY_GAPS: Final[tuple[str, ...]] = (
    "LIMIT, backtick quoting, catalog.schema.table and named :pN markers are rewritten to "
    "SQLite equivalents by declared rules; real Databricks SQL parsing is not exercised",
    "percentile_approx is emulated as an exact nearest-rank quantile; the real function is "
    "approximate and takes an optional accuracy parameter (default 10000) this adapter omits",
    "date_trunc('HOUR'|'DAY', ts) is emulated by string slicing of fixed-width ISO text; the real "
    "event_time is a TIMESTAMP and the string parameter relies on implicit cast",
    "Photon/serverless warehouse sizing, DBU cost, and engine-reported rows scanned are not "
    "modelled; the stub counts rows and charges a flat per-row cost",
    "warehouse cold start and autostop latency are not modelled",
    "Statement Execution API specifics (async polling, wait_timeout, inline result byte limits, "
    "external links, cancel endpoint) are not exercised; the executor seam is injected",
    "Entra token acquisition (managed identity, service principal) and Key Vault resolution "
    "are not exercised; no network or credential is touched in tests",
    "stub quoting: the stub scan counter matches the table as ANSI-quoted, so a declared "
    "rewrite normalises backticks before it runs",
)


def sqlite_shims(config: DatabricksConfig) -> tuple[Shim, ...]:
    """Shims that run Databricks-shaped SQL on the stub. Test-only; see ``G12_PARITY_GAPS``."""
    dialect_shim = Shim(
        name="databricks-dialect",
        description=(
            "collapses catalog.schema.table, rewrites backticks to double quotes, :pN markers to "
            "?, and date_trunc to ISO-text slicing"
        ),
        rules=(
            RewriteRule("drop-catalog", r"`[^`]+`\.(`[^`]+`\.`[^`]+`)", r"\1"),
            RewriteRule("backticks", r"`([^`]+)`", r'"\1"'),
            RewriteRule("named-markers", r":p\d+\b", "?"),
            RewriteRule(
                "date-trunc-hour",
                r"date_trunc\('HOUR', (\"[a-z_]+\")\)",
                r"(SUBSTR(\1, 1, 13) || ':00:00.000000Z')",
            ),
            RewriteRule(
                "date-trunc-day",
                r"date_trunc\('DAY', (\"[a-z_]+\")\)",
                r"(SUBSTR(\1, 1, 10) || 'T00:00:00.000000Z')",
            ),
            RewriteRule("quantile-name", r"percentile_approx\(", "PERCENTILE_APPROX("),
        ),
    )
    return (dialect_shim, *standard_shims("PERCENTILE_APPROX"))


class DatabricksAnalytics(SqlAnalytics):
    def __init__(self, config: DatabricksConfig, *, executor: SqlExecutor) -> None:
        super().__init__(
            backend=BACKEND,
            cloud=config.cloud,
            dialect=DatabricksDialect(catalog=config.catalog, schema=config.schema_name),
            executor=executor,
            schema=config.schema_name,
        )
        self.config = config

    def __repr__(self) -> str:
        return f"DatabricksAnalytics(cloud={self.cloud!r}, host={self.config.workspace_host!r})"


def create_adapter(
    *,
    cloud: str,
    region: str,
    config: Mapping[str, Any],
    executor: object | None,
) -> DatabricksAnalytics:
    """Registry entry point. ``executor`` is required: no databricks client is bundled."""
    if executor is None:
        raise InvalidSchemaError(
            "the databricks adapter needs an injected SqlExecutor", reason="databricks_executor"
        )
    for key, requested in (("cloud", cloud), ("region", region)):
        if key in config and config[key] != requested:
            raise InvalidSchemaError(f"config {key} differs from the request", reason=key)
    try:
        validated = DatabricksConfig.model_validate({**config, "cloud": cloud, "region": region})
    except ValidationError as exc:
        # Field names only: never echo input values (they could carry a credential).
        fields = sorted({".".join(str(p) for p in e["loc"]) or "config" for e in exc.errors()})
        raise InvalidSchemaError(
            "invalid databricks config: " + ", ".join(fields), reason="databricks_config"
        ) from None
    return DatabricksAnalytics(validated, executor=executor)  # type: ignore[arg-type]
