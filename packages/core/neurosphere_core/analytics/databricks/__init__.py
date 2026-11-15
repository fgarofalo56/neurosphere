"""Azure Databricks SQL warehouse analytics adapter (PRP-11 items 4, round 2 item 2)."""

from neurosphere_core.analytics.databricks.adapter import (
    G12_PARITY_GAPS,
    DatabricksAnalytics,
    create_adapter,
    sqlite_shims,
)
from neurosphere_core.analytics.databricks.config import DatabricksConfig
from neurosphere_core.analytics.databricks.dialect import DatabricksDialect
from neurosphere_core.analytics.databricks.executor import (
    DATABRICKS_SCOPE,
    DatabricksStatementExecutor,
    ExecutorError,
    build_statement_body,
    open_databricks_executor,
)
from neurosphere_core.analytics.databricks.migrations import (
    MIGRATIONS,
    SQLITE_MIGRATION_REWRITES,
    apply_migrations,
)

__all__ = [
    "DATABRICKS_SCOPE",
    "G12_PARITY_GAPS",
    "MIGRATIONS",
    "SQLITE_MIGRATION_REWRITES",
    "DatabricksAnalytics",
    "DatabricksConfig",
    "DatabricksDialect",
    "DatabricksStatementExecutor",
    "ExecutorError",
    "apply_migrations",
    "build_statement_body",
    "create_adapter",
    "open_databricks_executor",
    "sqlite_shims",
]
