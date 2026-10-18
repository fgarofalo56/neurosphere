"""T-SQL dialect for Microsoft Fabric Data Warehouse / lakehouse SQL analytics endpoint.

Fragments the shared renderer needs (PRP-11, ADR-0007):

* ``TOP (n)`` after SELECT (T-SQL has no LIMIT);
* bracket-quoted identifiers, ``]`` doubled;
* ``?`` ODBC positional placeholders;
* ``APPROX_PERCENTILE_CONT(q) WITHIN GROUP (ORDER BY col)`` for approximate quantiles;
* ``DATETRUNC(day|hour, col)`` for time buckets.

Microsoft Learn citations (observed 2026-10-18): the Fabric Data Warehouse T-SQL surface area
page (https://learn.microsoft.com/fabric/data-warehouse/tsql-surface-area) and the
``APPROX_PERCENTILE_CONT`` / ``DATETRUNC`` Transact-SQL references
(https://learn.microsoft.com/sql/t-sql/functions/approx-percentile-cont-transact-sql,
https://learn.microsoft.com/sql/t-sql/functions/datetrunc-transact-sql).

HONESTY NOTE: the Microsoft Learn MCP tools were NOT reachable in the session that wrote this
module, so those pages were not re-fetched and support for each function in Fabric Data
Warehouse is UNVERIFIED here. It is listed as a G12 / G01 gap; the live gate (Item 6) is what
confirms it. Stub tests prove the renderer and the contract, never this dialect's validity.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from neurosphere_core.analytics.base.models import Granularity
from neurosphere_core.analytics.base.records import format_timestamp


class FabricDialect:
    name = "fabric-tsql"

    def placeholder(self, index: int) -> str:
        return "?"

    def quote_identifier(self, name: str) -> str:
        return "[" + name.replace("]", "]]") + "]"

    def select_prefix(self, limit: int) -> str:
        return f"TOP ({int(limit)}) "

    def limit_suffix(self, limit: int) -> str:
        return ""

    def approx_quantile(self, column_sql: str, q: Decimal) -> str:
        return f"APPROX_PERCENTILE_CONT({format(q, 'f')}) WITHIN GROUP (ORDER BY {column_sql})"

    def time_bucket(self, column_sql: str, granularity: Granularity) -> str:
        part = "hour" if granularity is Granularity.HOUR else "day"
        return f"DATETRUNC({part}, {column_sql})"

    def timestamp_param(self, value: datetime) -> object:
        # Bound as fixed-width ISO-8601 text (UTC). Whether the engine accepts the trailing Z in
        # an implicit varchar -> datetime2 conversion is unverified: G12 gap.
        return format_timestamp(value)


__all__ = ["FabricDialect"]
