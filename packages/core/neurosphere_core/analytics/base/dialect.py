"""Shared SQL spine: the ``Dialect`` protocol and the renderer (PRP-11, ADR-0007).

The renderer turns a ``QueryPlan`` into ``Statement(sql, params)``. Safety rests on two facts:

* every identifier (columns, table) comes from the closed ``Column`` whitelist or the fixed
  table name, never from a request; an optional schema name must match a strict pattern;
* every caller or scope value is a bound parameter, in textual order of the placeholders.

The only literals in the text are validated numbers (the row limit and the quantile, typed
``int``/``Decimal`` upstream). Vendor adapters supply only a ``Dialect``; they do not edit this
module. SELECT layout (decoded by ``sql_adapter``): group keys, optional time bucket, metric
value, ``COUNT(*)`` (rows in group), ``COUNT(metric column)`` (known values).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from neurosphere_core.analytics.base.models import Aggregation, FilterOp, Granularity
from neurosphere_core.analytics.base.plan import (
    DIMENSION_COLUMN,
    METRIC_COLUMN,
    Column,
    Predicate,
    QueryPlan,
)
from neurosphere_core.analytics.base.records import ANALYTICS_TABLE, format_timestamp

_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


@dataclass(frozen=True)
class Statement:
    sql: str
    params: tuple[object, ...]


class Dialect(Protocol):
    """What a vendor adapter must say about its engine. Return fragments, never values."""

    name: str

    def placeholder(self, index: int) -> str:
        """Bound-parameter marker for the 1-based ``index`` (``?``, ``@p1``, ``:p1``, ``%s``)."""
        ...

    def quote_identifier(self, name: str) -> str:
        """Quote one whitelisted identifier (``"x"``, backticks, brackets)."""
        ...

    def select_prefix(self, limit: int) -> str:
        """Text after SELECT for row limiting (``"TOP 5 "``) or ``""``."""
        ...

    def limit_suffix(self, limit: int) -> str:
        """Trailing row limiting (``" LIMIT 5"``) or ``""``."""
        ...

    def approx_quantile(self, column_sql: str, q: Decimal) -> str:
        """Engine expression for an approximate quantile of an already-quoted column."""
        ...

    def time_bucket(self, column_sql: str, granularity: Granularity) -> str:
        """Engine expression truncating an already-quoted timestamp column."""
        ...

    def timestamp_param(self, value: datetime) -> object:
        """Bound value for a UTC instant (an ISO string, a datetime, ...)."""
        ...


class AnsiDialect:
    """Reference dialect for the stub and the contract tests. ``event_time`` is fixed-width ISO
    text. It proves the renderer, not any vendor's SQL."""

    name = "ansi-reference"

    def placeholder(self, index: int) -> str:
        return "?"

    def quote_identifier(self, name: str) -> str:
        return '"' + name.replace('"', '""') + '"'

    def select_prefix(self, limit: int) -> str:
        return ""

    def limit_suffix(self, limit: int) -> str:
        return f" LIMIT {int(limit)}"

    def approx_quantile(self, column_sql: str, q: Decimal) -> str:
        return f"PERCENTILE_APPROX({column_sql}, {q})"

    def time_bucket(self, column_sql: str, granularity: Granularity) -> str:
        if granularity is Granularity.HOUR:
            return f"(SUBSTR({column_sql}, 1, 13) || ':00:00.000000Z')"
        return f"(SUBSTR({column_sql}, 1, 10) || 'T00:00:00.000000Z')"

    def timestamp_param(self, value: datetime) -> object:
        return format_timestamp(value)


def _table(dialect: Dialect, schema: str | None) -> str:
    table = dialect.quote_identifier(ANALYTICS_TABLE)
    if schema is None:
        return table
    if not _SCHEMA_RE.match(schema):
        raise ValueError("schema must be a plain identifier")
    return f"{dialect.quote_identifier(schema)}.{table}"


def _metric_expr(dialect: Dialect, plan: QueryPlan) -> tuple[str, str]:
    """(aggregate expression, known-count expression)."""
    column = METRIC_COLUMN[plan.metric]
    if column is None:
        return "COUNT(*)", "COUNT(*)"
    col = dialect.quote_identifier(column.value)
    known = f"COUNT({col})"
    match plan.aggregation:
        case Aggregation.COUNT:
            return known, known
        case Aggregation.SUM:
            return f"SUM({col})", known
        case Aggregation.MIN:
            return f"MIN({col})", known
        case Aggregation.MAX:
            return f"MAX({col})", known
        case Aggregation.APPROX_QUANTILE:
            if plan.quantile is None:
                raise ValueError("approx_quantile needs a quantile")
            return dialect.approx_quantile(col, plan.quantile), known
    raise ValueError("unsupported aggregation")  # pragma: no cover


def _predicate(dialect: Dialect, pred: Predicate, params: list[object]) -> str:
    col = dialect.quote_identifier(Column(pred.column).value)

    def bind(value: object) -> str:
        params.append(value)
        return dialect.placeholder(len(params))

    match pred.op:
        case FilterOp.EQ:
            return f"{col} = {bind(pred.values[0])}"
        case FilterOp.IN:
            if not pred.values:
                raise ValueError("an empty IN list is never rendered; short-circuit instead")
            return f"{col} IN ({', '.join(bind(v) for v in pred.values)})"
        case FilterOp.IS_UNKNOWN:
            return f"{col} IS NULL"
    raise ValueError("unsupported operator")  # pragma: no cover


def render_statement(plan: QueryPlan, dialect: Dialect, *, schema: str | None = None) -> Statement:
    """Render ``plan`` for ``dialect``. Fetches ``plan.limit + 1`` rows so a breach of the
    returned-row limit is detectable (it raises ``rate_limited``, never truncates silently)."""
    if plan.matches_nothing:
        raise ValueError("a plan that matches nothing must not be rendered")
    params: list[object] = []
    keys = [dialect.quote_identifier(DIMENSION_COLUMN[d].value) for d in plan.group_by]
    if plan.time_bucket is not None:
        event_time = dialect.quote_identifier(Column.EVENT_TIME.value)
        keys.append(dialect.time_bucket(event_time, plan.time_bucket))
    value_expr, known_expr = _metric_expr(dialect, plan)
    select_list = ", ".join([*keys, value_expr, "COUNT(*)", known_expr])

    clauses = [_predicate(dialect, p, params) for p in plan.predicates]
    time_col = dialect.quote_identifier(Column.EVENT_TIME.value)
    params.append(dialect.timestamp_param(plan.time_start))
    clauses.append(f"{time_col} >= {dialect.placeholder(len(params))}")
    params.append(dialect.timestamp_param(plan.time_end))
    clauses.append(f"{time_col} < {dialect.placeholder(len(params))}")

    fetch = plan.limit + 1
    # S608: identifiers above come only from the closed Column whitelist / fixed table name
    # (schema is pattern-checked) and every value is a bound parameter; the remaining
    # interpolations are validated ints and a Decimal quantile.
    sql = (
        f"SELECT {dialect.select_prefix(fetch)}{select_list} "  # noqa: S608
        f"FROM {_table(dialect, schema)} WHERE {' AND '.join(clauses)}"
    )
    if keys:
        sql += f" GROUP BY {', '.join(keys)}"
    sql += dialect.limit_suffix(fetch)
    return Statement(sql=sql, params=tuple(params))


__all__ = ["AnsiDialect", "Dialect", "Statement", "render_statement"]
