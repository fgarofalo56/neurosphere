"""Fabric adapter over the stub SQL endpoint: contract conformance ONLY (PRP-11 item 2).

Nothing here is evidence that Fabric works in any cloud or region; see ``G12_PARITY_GAPS``.
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
from typing import Any

import pytest
from neurosphere_core.analytics.base import (
    AggregateRequest,
    ExecutionLimits,
    ExecutionOutcome,
    Statement,
    StubSqlEndpoint,
    compare_results,
)
from neurosphere_core.analytics.base import create_adapter as registry_create
from neurosphere_core.analytics.base.records import ANALYTICS_TABLE
from neurosphere_core.analytics.fabric import (
    G12_PARITY_GAPS,
    MIGRATIONS,
    FabricAnalytics,
    FabricConfig,
    FabricDialect,
    Migration,
    apply_migrations,
    create_adapter,
    fabric_stub_shims,
)
from neurosphere_core.analytics.fabric.migrations import LEDGER_TABLE, validate_migration_set
from neurosphere_core.analytics.fixture import build_dataset
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    InvalidSchemaError,
    RateLimitedError,
)
from pydantic import ValidationError

from .analytics_helpers import fixture_adapter, make_budget, make_request, make_scope
from .test_fixture_equivalence import CASES

COMMERCIAL_HOST = "abc123.datawarehouse.fabric.microsoft.com"
GOV_HOST = "abc123.fabric.microsoft.us"


def commercial_config(**over: Any) -> dict[str, Any]:
    return {
        "cloud": "commercial",
        "region": "eastus2",
        "sql_endpoint_host": COMMERCIAL_HOST,
        "database": "ns_analytics",
        **over,
    }


def gov_config(**over: Any) -> dict[str, Any]:
    return {
        "cloud": "government",
        "region": "usgovvirginia",
        "sql_endpoint_host": GOV_HOST,
        "database": "ns_analytics",
        **over,
    }


def fabric_adapter(cloud: str = "commercial") -> tuple[FabricAnalytics, StubSqlEndpoint]:
    endpoint = StubSqlEndpoint(
        build_dataset(cloud),  # type: ignore[arg-type]
        shims=fabric_stub_shims(),
        schema="dbo",
    )
    cfg = commercial_config() if cloud == "commercial" else gov_config()
    adapter = create_adapter(cloud=cloud, region=cfg["region"], config=cfg, executor=endpoint)
    return adapter, endpoint


# --- equivalence ---------------------------------------------------------------------------


@pytest.mark.parametrize(("name", "request_"), CASES, ids=[c[0] for c in CASES])
async def test_fabric_equals_fixture(name: str, request_: AggregateRequest) -> None:
    adapter, endpoint = fabric_adapter()
    expected = await fixture_adapter().aggregate(request_, scope=make_scope())
    actual = await adapter.aggregate(request_, scope=make_scope())
    assert compare_results(expected, actual) == []
    assert expected.rows
    assert actual.backend == "fabric"
    assert actual.stats.rows_scanned == endpoint.row_count  # scan counter survived the rewrites
    assert any(n == "fabric-tsql-rewrite" for n, _ in endpoint.applied_shims)


async def test_government_dataset_equivalence() -> None:
    adapter, _ = fabric_adapter("government")
    scope = make_scope("government", "contoso", ("retail", "support"))
    for _, request_ in CASES:
        expected = await fixture_adapter("government").aggregate(request_, scope=scope)
        assert compare_results(expected, await adapter.aggregate(request_, scope=scope)) == []
    assert adapter.cloud == "government"


async def test_null_groups_stay_unknown() -> None:
    from neurosphere_core.analytics.base import Aggregation, Dimension, Metric

    adapter, _ = fabric_adapter()
    result = await adapter.aggregate(
        make_request(Metric.OUTPUT_TOKENS, Aggregation.MAX, group_by=(Dimension.MODEL,)),
        scope=make_scope(),
    )
    legacy = next(r for r in result.rows if r.keys == ("embed-legacy",))
    assert legacy.value is None and legacy.unknown_count == legacy.row_count


# --- emitted SQL ---------------------------------------------------------------------------


async def test_emitted_sql_is_tsql_with_bound_values() -> None:
    from neurosphere_core.analytics.base import (
        Aggregation,
        Dimension,
        FilterClause,
        FilterOp,
        Granularity,
        Metric,
        build_plan,
        render_statement,
    )

    request_ = make_request(
        Metric.DURATION_MS,
        Aggregation.APPROX_QUANTILE,
        quantile=0.95,
        time_bucket=Granularity.DAY,
        group_by=(Dimension.MODEL,),
        filters=(FilterClause(field=Dimension.PROVIDER, op=FilterOp.EQ, values=("anthropic",)),),
    )
    plan = build_plan(request_, make_scope(), "commercial")
    statement = render_statement(plan, FabricDialect(), schema="dbo")
    sql = statement.sql
    assert sql.startswith("SELECT TOP (")
    assert "[dbo].[" + ANALYTICS_TABLE + "]" in sql and "[model]" in sql
    assert '"' not in sql and "LIMIT" not in sql
    assert "DATETRUNC(day, [event_time])" in sql
    assert "APPROX_PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY [duration_ms])" in sql
    assert "anthropic" not in sql and "contoso" not in sql  # values are parameters
    assert sql.count("?") == len(statement.params)
    assert "anthropic" in statement.params and "contoso" in statement.params


async def test_endpoint_sees_rewritten_statement() -> None:
    adapter, endpoint = fabric_adapter()
    await adapter.aggregate(make_request(), scope=make_scope())
    assert endpoint.last_sql is not None
    assert "TOP" not in endpoint.last_sql and "LIMIT" in endpoint.last_sql


def test_dialect_quotes_and_prefix() -> None:
    d = FabricDialect()
    assert d.quote_identifier("a]b") == "[a]]b]"
    assert d.select_prefix(5) == "TOP (5) " and d.limit_suffix(5) == ""
    assert d.placeholder(3) == "?"


# --- config and cloud boundary -------------------------------------------------------------


def test_valid_configs_construct() -> None:
    assert FabricConfig.model_validate(commercial_config()).read_only is False
    assert FabricConfig.model_validate(gov_config(region="usgovtexas")).cloud == "government"
    lake = FabricConfig.model_validate(commercial_config(item_kind="lakehouse_sql_endpoint"))
    assert lake.read_only


@pytest.mark.parametrize(
    "bad",
    [
        gov_config(sql_endpoint_host=COMMERCIAL_HOST),  # Government with a Commercial host
        commercial_config(sql_endpoint_host=GOV_HOST),  # Commercial with a Government host
        gov_config(region="eastus2"),  # Commercial region for Government
        gov_config(region="usgovarizona"),  # Government region without Fabric GCC High
        commercial_config(region="usgovvirginia"),
        commercial_config(sql_endpoint_host="https://" + COMMERCIAL_HOST),
        commercial_config(sql_endpoint_host=COMMERCIAL_HOST + ":1433"),
        commercial_config(sql_endpoint_host="abc.tenant.fabric.microsoft.com"),
        commercial_config(sql_endpoint_host=COMMERCIAL_HOST.upper()),
        commercial_config(item_kind="eventhouse"),
        commercial_config(**{"pass" + "word": "x"}),  # no secret fields at all
        commercial_config(auth_mode="sql_password"),
    ],
)
def test_bad_configs_fail_at_construction(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        FabricConfig.model_validate(bad)
    with pytest.raises(InvalidSchemaError):
        create_adapter(cloud=bad["cloud"], region=bad["region"], config=bad, executor=_Dummy())


def test_config_is_frozen_and_has_no_secret_field() -> None:
    cfg = FabricConfig.model_validate(commercial_config())
    with pytest.raises(ValidationError):
        cfg.database = "other"  # type: ignore[misc]
    assert not [f for f in FabricConfig.model_fields if re.search(r"secret|password|key|token", f)]


def test_create_adapter_requires_executor_and_consistent_args() -> None:
    with pytest.raises(InvalidSchemaError) as missing:
        create_adapter(
            cloud="commercial", region="eastus2", config=commercial_config(), executor=None
        )
    assert missing.value.reason == "fabric_executor_required"
    with pytest.raises(InvalidSchemaError):  # config cloud contradicts the requested cloud
        create_adapter(
            cloud="government",
            region="usgovvirginia",
            config=commercial_config(),
            executor=_Dummy(),
        )


def test_registry_loads_fabric_for_government_when_matrix_allows() -> None:
    adapter = registry_create(
        "fabric",
        cloud="government",
        region="usgovvirginia",
        config=gov_config(),
        executor=_Dummy(),
    )
    assert adapter.cloud == "government" and adapter.backend == "fabric"


# --- feature flags from the matrix ---------------------------------------------------------


@pytest.mark.parametrize("region", ["usgovvirginia", "usgovtexas"])
def test_gcc_high_features_disabled_with_matrix_reason(region: str) -> None:
    adapter = create_adapter(
        cloud="government", region=region, config=gov_config(region=region), executor=_Dummy()
    )
    flags = adapter.feature_flags
    for flag in (flags.customer_managed_keys, flags.workspace_identity, flags.fabric_iq_items):
        assert flag.enabled is False
        assert flag.row_id is not None and flag.row_id.startswith("fabric.")
        assert flag.reason and "us-government-community-cloud-high" in flag.reason
        assert flag.reason_code == "not_available_in_region"


def test_commercial_features_are_not_assumed_enabled() -> None:
    flags = fabric_adapter()[0].feature_flags
    # No Commercial rows exist: unverified means disabled, never a hard-coded true.
    assert not flags.customer_managed_keys.enabled
    assert flags.customer_managed_keys.reason_code == "not_verified"


# --- budgets -------------------------------------------------------------------------------


class _Dummy:
    async def execute(self, statement: Statement, *, limits: ExecutionLimits) -> ExecutionOutcome:
        raise AssertionError("not executed")


class _Slow:
    def __init__(self) -> None:
        self.cancelled = False

    async def execute(self, statement: Statement, *, limits: ExecutionLimits) -> ExecutionOutcome:
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        raise AssertionError("should have been cancelled")


async def test_time_budget_enforced_through_adapter() -> None:
    slow = _Slow()
    adapter = create_adapter(
        cloud="commercial", region="eastus2", config=commercial_config(), executor=slow
    )
    with pytest.raises(RateLimitedError) as err:
        await adapter.aggregate(make_request(budget=make_budget(timeout_ms=50)), scope=make_scope())
    assert err.value.reason == "time_budget_exceeded"
    assert slow.cancelled


async def test_rows_budget_enforced_through_adapter() -> None:
    adapter, _ = fabric_adapter()
    with pytest.raises(RateLimitedError) as err:
        await adapter.aggregate(
            make_request(budget=make_budget(max_rows_scanned=10)), scope=make_scope()
        )
    assert err.value.reason == "rows_scanned_budget_exceeded"


# --- migrations ----------------------------------------------------------------------------


class _SqliteMigrations:
    """MigrationExecutor over in-memory SQLite with the OBJECT_ID guard declared as a rewrite
    (G12: SQLite is not T-SQL). ``[x]`` quoting is native to SQLite."""

    GUARD = re.compile(r"IF OBJECT_ID\(N'[^']*', N'U'\) IS NULL CREATE TABLE")

    def __init__(self, schema: str = "dbo") -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(f"ATTACH DATABASE ':memory:' AS {schema}")
        self.statements: list[str] = []

    async def run(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.statements.append(sql)
        self.conn.execute(self.GUARD.sub("CREATE TABLE IF NOT EXISTS", sql), params)

    async def query(self, sql: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
        return [tuple(r) for r in self.conn.execute(sql, params).fetchall()]


def test_migration_set_is_versioned_and_monotonic() -> None:
    validate_migration_set(MIGRATIONS)
    assert [m.id for m in MIGRATIONS] == ["V001__schema_ledger", "V002__analytics_events"]
    with pytest.raises(ValueError):
        validate_migration_set((MIGRATIONS[1], MIGRATIONS[0]))
    with pytest.raises(ValueError):
        validate_migration_set((Migration(1, "ok_name", ("x",)), Migration(3, "gap", ("x",))))
    for m in MIGRATIONS:  # every DDL statement is guarded for idempotency, none destructive
        for s in m.statements:
            assert s.startswith("IF OBJECT_ID(") and "DROP" not in s.upper()


async def test_migrations_apply_once_and_are_idempotent() -> None:
    cfg = FabricConfig.model_validate(commercial_config())
    ex = _SqliteMigrations()
    first = await apply_migrations(ex, config=cfg)
    assert (
        first.applied == ("V001__schema_ledger", "V002__analytics_events")
        and not first.already_applied
    )
    second = await apply_migrations(ex, config=cfg)
    assert second.applied == () and len(second.already_applied) == 2
    ledger = ex.conn.execute(
        f"SELECT version, name FROM dbo.{LEDGER_TABLE} ORDER BY version"  # noqa: S608
    ).fetchall()
    assert ledger == [(1, "schema_ledger"), (2, "analytics_events")]
    cols = {r[1] for r in ex.conn.execute(f"PRAGMA dbo.table_info({ANALYTICS_TABLE})")}
    assert {"event_id", "event_time", "cost_amount", "domain_id"} <= cols


async def test_migrated_table_serves_the_adapter_dialect() -> None:
    cfg = FabricConfig.model_validate(commercial_config())
    ex = _SqliteMigrations()
    await apply_migrations(ex, config=cfg)
    # the table the migration created has every column the renderer selects
    from neurosphere_core.analytics.base.plan import Column

    cols = {r[1] for r in ex.conn.execute(f"PRAGMA dbo.table_info({ANALYTICS_TABLE})")}
    assert {c.value for c in Column} <= cols


async def test_migration_checksum_drift_is_detected() -> None:
    cfg = FabricConfig.model_validate(commercial_config())
    ex = _SqliteMigrations()
    await apply_migrations(ex, config=cfg)
    edited = (
        MIGRATIONS[0],
        Migration(
            2,
            "analytics_events",
            ("IF OBJECT_ID(N'x', N'U') IS NULL CREATE TABLE {schema}.[t] (a int)",),
        ),
    )
    with pytest.raises(CapabilityUnavailableError) as err:
        await apply_migrations(ex, config=cfg, migrations=edited)
    assert err.value.reason == "migration_checksum_mismatch"


async def test_migrations_refused_on_read_only_item() -> None:
    cfg = FabricConfig.model_validate(commercial_config(item_kind="lakehouse_sql_endpoint"))
    ex = _SqliteMigrations()
    with pytest.raises(CapabilityUnavailableError) as err:
        await apply_migrations(ex, config=cfg)
    assert err.value.reason == "fabric_item_read_only"
    assert ex.statements == []  # nothing ran


def test_g12_gaps_are_declared() -> None:
    text = " ".join(G12_PARITY_GAPS).lower()
    for needle in ("top", "quantile", "throttl", "entra", "capacity", "inferred, unverified"):
        assert needle in text
