from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from neurosphere_core.analytics.base import (
    AnsiDialect,
    ExecutionLimits,
    RewriteRule,
    Shim,
    SqlAnalytics,
    Statement,
    StubSqlEndpoint,
    build_plan,
    render_statement,
    standard_shims,
)
from neurosphere_core.analytics.base.models import Dimension, Granularity
from neurosphere_core.analytics.fixture import build_dataset

from .analytics_helpers import make_request, make_scope

LIMITS = ExecutionLimits(max_rows_scanned=10_000, max_cost_units=Decimal(1000))


def test_renderer_uses_parameters_for_every_value() -> None:
    request = make_request(group_by=(Dimension.MODEL,), time_bucket=Granularity.DAY)
    plan = build_plan(request, make_scope(), "commercial")
    statement = render_statement(plan, AnsiDialect())
    assert "contoso" not in statement.sql and "commercial" not in statement.sql
    assert "contoso" in statement.params and "commercial" in statement.params
    assert statement.sql.count("?") == len(statement.params)
    assert statement.sql.startswith("SELECT ")
    assert 'FROM "ns_analytics_events"' in statement.sql
    assert statement.sql.endswith(f"LIMIT {plan.limit + 1}")


def test_schema_name_must_be_a_plain_identifier() -> None:
    plan = build_plan(make_request(), make_scope(), "commercial")
    with pytest.raises(ValueError, match="plain identifier"):
        render_statement(plan, AnsiDialect(), schema='x"; DROP TABLE t;--')
    assert '"ns"."ns_analytics_events"' in render_statement(plan, AnsiDialect(), schema="ns").sql


async def test_stub_runs_a_schema_qualified_statement() -> None:
    records = build_dataset("commercial", 50)
    endpoint = StubSqlEndpoint(records, shims=standard_shims(), schema="ns")
    adapter = SqlAnalytics(
        backend="stub", cloud="commercial", dialect=AnsiDialect(), executor=endpoint, schema="ns"
    )
    result = await adapter.aggregate(make_request(), scope=make_scope())
    assert result.rows


async def test_shims_are_listed_and_rewrites_apply() -> None:
    class AtDialect(AnsiDialect):
        name = "at-params"

        def placeholder(self, index: int) -> str:
            return f"@p{index}"

    shim = Shim(
        name="at-params",
        description="@pN placeholders rewritten to ?N",
        rules=(RewriteRule("at-to-qmark", r"@p(\d+)", r"?\1"),),
    )
    endpoint = StubSqlEndpoint(build_dataset("commercial", 60), shims=(*standard_shims(), shim))
    names = [n for n, _ in endpoint.applied_shims]
    assert names[-1] == "scan-counter" and "at-params" in names and "decimal-cost" in names
    adapter = SqlAnalytics(
        backend="stub", cloud="commercial", dialect=AtDialect(), executor=endpoint
    )
    result = await adapter.aggregate(make_request(), scope=make_scope())
    assert result.rows
    assert "@p" not in (endpoint.last_sql or "")


async def test_stub_accepts_select_only() -> None:
    endpoint = StubSqlEndpoint(build_dataset("commercial", 5), shims=standard_shims())
    with pytest.raises(ValueError, match="SELECT"):
        await endpoint.execute(Statement("DELETE FROM ns_analytics_events", ()), limits=LIMITS)
    with pytest.raises(ValueError, match="analytics table"):
        await endpoint.execute(Statement("SELECT 1", ()), limits=LIMITS)


async def test_time_bucket_is_decoded_as_utc_datetime() -> None:
    endpoint = StubSqlEndpoint(build_dataset("commercial", 100), shims=standard_shims())
    adapter = SqlAnalytics(
        backend="stub", cloud="commercial", dialect=AnsiDialect(), executor=endpoint
    )
    result = await adapter.aggregate(make_request(time_bucket=Granularity.HOUR), scope=make_scope())
    assert all(isinstance(r.bucket, datetime) and r.bucket.minute == 0 for r in result.rows)
