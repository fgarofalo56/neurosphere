"""Azure Synapse SQL analytics adapter: serverless and dedicated modes (PRP-11 item 3).

Mode is chosen by ``SynapseConfig.mode``. See ``dialect`` for the per-mode T-SQL decisions and
Microsoft Learn citations, ``config`` for the cloud boundary, ``migrations`` for versioned DDL.
Stub-based tests prove contract conformance only; they are not evidence that Synapse works in a
cloud or region (only the operator-approved live gate is).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from neurosphere_core.analytics.base import Cloud, SqlExecutor
from neurosphere_core.analytics.synapse.adapter import SynapseAnalytics
from neurosphere_core.analytics.synapse.config import SynapseConfig
from neurosphere_core.analytics.synapse.dialect import (
    SynapseDedicatedDialect,
    SynapseServerlessDialect,
)
from neurosphere_core.analytics.synapse.migrations import (
    Migration,
    MigrationError,
    MigrationExecutor,
    apply_migrations,
    migrations_for,
)
from neurosphere_core.errors import InvalidSchemaError

# G12 emulator-parity gaps: what the SQLite stub cannot reproduce for Synapse.
G12_PARITY_GAPS: Final[tuple[str, ...]] = (
    "T-SQL rewrites: SELECT TOP n becomes LIMIT n; [bracket] quoting becomes double quotes before "
    "the stub scan counter (whose regex matches the ANSI-quoted table name); OPTION (LABEL) is "
    "stripped; DATEADD/DATEDIFF bucketing is replaced by SUBSTR on ISO text. Synapse acceptance "
    "of the real text is untested.",
    "Quantile: neither mode has an approximate quantile, so the adapter refuses it "
    "(CapabilityUnavailableError); the stub cannot show that PERCENTILE_CONT window use is "
    "impractical here, nor any future engine-side function.",
    "Billing: serverless bills data processed (TB), dedicated bills DWU-hours; the stub's cost "
    "units are a flat per-row figure and match neither.",
    "Concurrency and throttling: dedicated resource classes and concurrency slots, serverless "
    "concurrency limits and request queuing are not modelled.",
    "Authentication: Entra / managed-identity token acquisition and its Government authority "
    "(login.microsoftonline.us) are not exercised; the stub has no auth.",
    "Serverless cold start and OPENROWSET Parquet schema inference/collation behaviour are not "
    "modelled; DDL (distribution, columnstore, statistics, external data source) runs only as "
    "rewritten no-ops or plain SQLite DDL.",
    "Decimal fidelity: DECIMAL(38,12) native arithmetic is emulated by Python Decimal shims.",
)


def create_adapter(
    *,
    cloud: str,
    region: str,
    config: Mapping[str, Any],
    executor: object | None,
) -> SynapseAnalytics:
    """Registry entry point (``neurosphere_core.analytics.synapse:create_adapter``).

    The executor is required: no database driver ships with the core package (operator
    decision), so the caller injects a ``SqlExecutor`` for the chosen endpoint."""
    if executor is None:
        raise InvalidSchemaError(
            "the Synapse adapter needs an injected SqlExecutor (no driver is bundled)",
            reason="synapse_executor_required",
        )
    typed: Cloud = "government" if cloud == "government" else "commercial"
    if cloud not in ("commercial", "government"):
        raise InvalidSchemaError(f"unknown cloud {cloud!r}", reason="synapse_cloud")
    sql_executor: SqlExecutor = executor  # type: ignore[assignment]
    return SynapseAnalytics(cloud=typed, region=region, config=config, executor=sql_executor)


__all__ = [
    "G12_PARITY_GAPS",
    "Migration",
    "MigrationError",
    "MigrationExecutor",
    "SynapseAnalytics",
    "SynapseConfig",
    "SynapseDedicatedDialect",
    "SynapseServerlessDialect",
    "apply_migrations",
    "create_adapter",
    "migrations_for",
]
