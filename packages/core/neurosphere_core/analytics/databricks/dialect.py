"""Databricks SQL dialect for the shared renderer (PRP-11 item 4).

Sources (Microsoft Learn, Azure Databricks language manual), observed 2026-10-18. The
orchestrator verified on Learn that named ``:name`` markers are supplied by the Statement
Execution API and cannot be mixed with ``?``; that ``approx_percentile`` is a synonym of
``percentile_approx`` (default accuracy 10000, relative error 1/accuracy); and that
``date_trunc(unit, expr)`` accepts DATE, TIMESTAMP or STRING. Documentation is not execution;
the live gate (G12) confirms behaviour:

* identifiers, backtick quoting:
  https://learn.microsoft.com/azure/databricks/sql/language-manual/sql-ref-identifiers
* row limiting, ``LIMIT n`` after GROUP BY:
  https://learn.microsoft.com/azure/databricks/sql/language-manual/sql-ref-syntax-qry-select-limit
* parameter markers (named ``:name``; unnamed ``?``):
  https://learn.microsoft.com/azure/databricks/sql/language-manual/sql-ref-parameter-marker
* ``percentile_approx(expr, percentile [, accuracy])``:
  https://learn.microsoft.com/azure/databricks/sql/language-manual/functions/percentile_approx
* ``date_trunc(unit, expr)``:
  https://learn.microsoft.com/azure/databricks/sql/language-manual/functions/date_trunc
* SQL Statement Execution API (``parameters`` carry a name, value and type):
  https://learn.microsoft.com/azure/databricks/dev-tools/sql-execution-tutorial

Parameter markers: NAMED (``:p1``, ``:p2`` ...). The Statement Execution API binds a list of
``{name, value, type}`` entries, so a named marker maps one-to-one onto an API parameter and a
reordered or duplicated reference can never silently mis-bind. The renderer numbers markers in
textual order, so ``params[i]`` is bound to ``:p{i+1}``. Values are never interpolated.

Namespace: Databricks uses catalog.schema.table. The shared renderer qualifies a table with ONE
schema part, so this dialect renders the pair ``catalog``.``schema`` when it is asked to quote the
configured schema name (both come from the validated config; neither is a column name, which is
enforced at construction).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from neurosphere_core.analytics.base.dialect import Dialect
from neurosphere_core.analytics.base.models import Granularity
from neurosphere_core.analytics.base.plan import Column
from neurosphere_core.analytics.base.records import ANALYTICS_TABLE, format_timestamp

_RESERVED = {c.value for c in Column} | {ANALYTICS_TABLE}


def _backtick(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


class DatabricksDialect:
    name = "databricks-sql"

    def __init__(self, *, catalog: str, schema: str) -> None:
        if schema in _RESERVED or catalog in _RESERVED:
            raise ValueError("catalog and schema must not collide with column or table names")
        self._catalog = catalog
        self._schema = schema

    def placeholder(self, index: int) -> str:
        return f":p{int(index)}"

    def quote_identifier(self, name: str) -> str:
        if name == self._schema:
            return f"{_backtick(self._catalog)}.{_backtick(name)}"
        return _backtick(name)

    def select_prefix(self, limit: int) -> str:
        return ""

    def limit_suffix(self, limit: int) -> str:
        return f" LIMIT {int(limit)}"

    def approx_quantile(self, column_sql: str, q: Decimal) -> str:
        return f"percentile_approx({column_sql}, {q})"

    def time_bucket(self, column_sql: str, granularity: Granularity) -> str:
        unit = "HOUR" if granularity is Granularity.HOUR else "DAY"
        return f"date_trunc('{unit}', {column_sql})"

    def timestamp_param(self, value: datetime) -> object:
        # Fixed-width UTC ISO text; the executor binds it with API type TIMESTAMP (G12 gap).
        return format_timestamp(value)


_: Dialect = DatabricksDialect(catalog="c", schema="s")
