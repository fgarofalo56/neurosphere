"""Azure Databricks SQL warehouse analytics adapter (PRP-11 item 4)."""

from neurosphere_core.analytics.databricks.adapter import (
    G12_PARITY_GAPS,
    DatabricksAnalytics,
    create_adapter,
    sqlite_shims,
)
from neurosphere_core.analytics.databricks.config import DatabricksConfig
from neurosphere_core.analytics.databricks.dialect import DatabricksDialect
from neurosphere_core.analytics.databricks.migrations import (
    MIGRATIONS,
    SQLITE_MIGRATION_REWRITES,
    apply_migrations,
)

__all__ = [
    "G12_PARITY_GAPS",
    "MIGRATIONS",
    "SQLITE_MIGRATION_REWRITES",
    "DatabricksAnalytics",
    "DatabricksConfig",
    "DatabricksDialect",
    "apply_migrations",
    "create_adapter",
    "sqlite_shims",
]
