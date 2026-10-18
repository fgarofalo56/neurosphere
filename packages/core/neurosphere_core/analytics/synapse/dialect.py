"""T-SQL dialects for Synapse serverless and dedicated SQL pools (PRP-11 item 3).

Per-mode feature decisions (observed 2026-10-18). The Microsoft Learn MCP tools were not
available to the author; the orchestrator's Learn lookup supplied the "Applies to" facts for
APPROX_PERCENTILE_CONT and DATETRUNC (SQL Server 2022, Azure SQL, Fabric only; Azure Synapse NOT
listed), PERCENTILE_CONT (Synapse listed, window form only) and DATEADD/DATEDIFF (Synapse
listed). The remaining points (OPTION LABEL, serverless limits) are unverified here; the live
gate (item 6) must confirm them:
* https://learn.microsoft.com/sql/t-sql/functions/approx-percentile-cont-transact-sql
* https://learn.microsoft.com/sql/t-sql/functions/datetrunc-transact-sql
* https://learn.microsoft.com/azure/synapse-analytics/sql/overview-features

* T-SQL surface, serverless: https://learn.microsoft.com/azure/synapse-analytics/sql/overview-features
* T-SQL surface, dedicated: https://learn.microsoft.com/azure/synapse-analytics/sql-data-warehouse/sql-data-warehouse-reference-tsql-statements
* Dedicated query label: https://learn.microsoft.com/azure/synapse-analytics/sql-data-warehouse/sql-data-warehouse-develop-label
* PERCENTILE_CONT (window function only): https://learn.microsoft.com/sql/t-sql/functions/percentile-cont-transact-sql

Decisions, identical in both modes unless stated:

* Row limit: ``SELECT TOP n``. No ``LIMIT``/``OFFSET`` without ``ORDER BY``; the cap only bounds
  the result (the adapter fetches limit+1 and raises on overflow), so no ORDER BY is needed.
* Parameters: ODBC ``?`` markers bound by the injected executor; values are never in the text.
* Time bucket: ``DATEADD(unit, DATEDIFF(unit, 0, col), 0)``. ``DATETRUNC`` is not relied on
  (not documented for Synapse pools). Result is a naive datetime read as UTC by the decoder.
* Approximate quantile: NOT SUPPORTED in either mode. Synapse has no ``APPROX_PERCENTILE_CONT``
  (that is SQL Server 2022 / Azure SQL / Fabric). ``PERCENTILE_CONT ... WITHIN GROUP`` exists only
  as an analytic (``OVER``) function, which cannot be expressed in the shared aggregate layout
  (one aggregate expression per group), and the exact value would not be "approximate" anyway.
  Both dialects therefore raise ``CapabilityUnavailableError`` for ``approx_quantile`` with a
  reason; nothing is faked or silently computed client-side.
* Dedicated only: ``OPTION (LABEL = 'ns_analytics')`` so queries are attributable in
  ``sys.dm_pdw_exec_requests``. Serverless does not accept it, so it is omitted there.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final

from neurosphere_core.analytics.base.models import Granularity
from neurosphere_core.analytics.base.records import format_timestamp
from neurosphere_core.errors import CapabilityUnavailableError

QUERY_LABEL: Final = "ns_analytics"
QUANTILE_REASON: Final = "synapse_no_approx_percentile"


class _TSqlDialect:
    name = "tsql"
    mode_label = ""

    def placeholder(self, index: int) -> str:
        return "?"

    def quote_identifier(self, name: str) -> str:
        return "[" + name.replace("]", "]]") + "]"

    def select_prefix(self, limit: int) -> str:
        return f"TOP {int(limit)} "

    def limit_suffix(self, limit: int) -> str:
        return ""

    def approx_quantile(self, column_sql: str, q: Decimal) -> str:
        raise CapabilityUnavailableError(
            QUANTILE_REASON,
            f"Synapse {self.mode_label} SQL has no approximate-quantile aggregate "
            "(PERCENTILE_CONT is window-only); approx_quantile is unavailable on this backend",
        )

    def time_bucket(self, column_sql: str, granularity: Granularity) -> str:
        unit = "hour" if granularity is Granularity.HOUR else "day"
        return f"DATEADD({unit}, DATEDIFF({unit}, 0, {column_sql}), 0)"

    def timestamp_param(self, value: datetime) -> object:
        # Fixed-width ISO 8601; implicitly converted to the datetime2 column type by the engine.
        return format_timestamp(value)


class SynapseServerlessDialect(_TSqlDialect):
    name = "synapse-serverless-tsql"
    mode_label = "serverless"


class SynapseDedicatedDialect(_TSqlDialect):
    name = "synapse-dedicated-tsql"
    mode_label = "dedicated"

    def limit_suffix(self, limit: int) -> str:
        return f" OPTION (LABEL = '{QUERY_LABEL}')"
