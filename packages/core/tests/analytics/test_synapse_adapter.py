"""Synapse adapter (serverless + dedicated) over the contract stub (PRP-11 item 3).

Contract conformance only: the SQLite stub plus declared T-SQL rewrite shims proves the emitted
statement SHAPE and the result equivalence, not that Synapse accepts it (see G12_PARITY_GAPS).
"""

# ruff: noqa: S608 - test SQL built from module constants only
from __future__ import annotations

import asyncio
import re
import sqlite3
from typing import Any, get_args

import pytest
from neurosphere_core.analytics import synapse
from neurosphere_core.analytics.base import (
    AggregateRequest,
    Aggregation,
    Cloud,
    Dimension,
    ExecutionLimits,
    ExecutionOutcome,
    Granularity,
    Metric,
    Statement,
    StubSqlEndpoint,
    compare_results,
)
from neurosphere_core.analytics.base import create_adapter as registry_create
from neurosphere_core.analytics.base.records import AnalyticsRecord
from neurosphere_core.analytics.fixture import build_dataset
from neurosphere_core.analytics.synapse.config import SynapseConfig
from neurosphere_core.analytics.synapse.migrations import (
    LEDGER_TABLE,
    MigrationError,
    migrations_for,
)
from neurosphere_core.analytics.synapse.stub_shims import synapse_stub_shims, tsql_ddl_shim
from neurosphere_core.errors import CapabilityUnavailableError, InvalidSchemaError, RateLimitedError

from .analytics_helpers import fixture_adapter, make_budget, make_request, make_scope
from .test_fixture_equivalence import CASES

MODES = ("serverless", "dedicated")
REGION: dict[str, str] = {"commercial": "eastus", "government": "usgovvirginia"}
SUFFIX: dict[str, str] = {
    "commercial": ".sql.azuresynapse.net",
    "government": ".sql.azuresynapse.usgovcloudapi.net",
}


def make_config(mode: str, **extra: Any) -> dict[str, Any]:
    return {
        "mode": mode,
        "workspace": "nsdemo",
        "database": "nsanalytics",
        **({"external_data_source": "ns_lake"} if mode == "serverless" else {}),
        **extra,
    }


class Recording:
    """Executor wrapper that remembers the Statement objects the adapter sent."""

    def __init__(self, inner: StubSqlEndpoint) -> None:
        self.inner = inner
        self.statements: list[Statement] = []

    async def execute(self, statement: Statement, *, limits: ExecutionLimits) -> ExecutionOutcome:
        self.statements.append(statement)
        return await self.inner.execute(statement, limits=limits)


def build(
    mode: str,
    cloud: Cloud = "commercial",
    records: tuple[AnalyticsRecord, ...] | None = None,
    **config_extra: Any,
) -> tuple[synapse.SynapseAnalytics, Recording, StubSqlEndpoint]:
    endpoint = StubSqlEndpoint(
        records if records is not None else build_dataset(cloud),
        shims=synapse_stub_shims(),
        schema="ns",
    )
    recording = Recording(endpoint)
    adapter = synapse.create_adapter(
        cloud=cloud,
        region=REGION[cloud],
        config=make_config(mode, **config_extra),
        executor=recording,
    )
    return adapter, recording, endpoint


# --- equivalence -----------------------------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(("name", "request_"), CASES, ids=[c[0] for c in CASES])
async def test_mode_equals_fixture(mode: str, name: str, request_: AggregateRequest) -> None:
    adapter, _, endpoint = build(mode)
    scope = make_scope()
    if request_.aggregation is Aggregation.APPROX_QUANTILE:
        with pytest.raises(CapabilityUnavailableError) as refusal:
            await adapter.aggregate(request_, scope=scope)
        assert refusal.value.reason == "synapse_no_approx_percentile"
        return
    expected = await fixture_adapter().aggregate(request_, scope=scope)
    actual = await adapter.aggregate(request_, scope=scope)
    assert compare_results(expected, actual) == []
    assert expected.rows
    assert actual.backend == f"synapse-{mode}"
    if request_.aggregation is Aggregation.MIN or request_.metric is Metric.COST_AMOUNT:
        assert any("decimal-cost" in n for n, _ in endpoint.applied_shims)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("cloud", get_args(Cloud))
async def test_both_clouds_and_null_groups(mode: str, cloud: Cloud) -> None:
    adapter, _, _ = build(mode, cloud)
    scope = make_scope(cloud, "fabrikam" if cloud == "commercial" else "contoso", ("finance",))
    request_ = make_request(group_by=(Dimension.DOMAIN_ID,))
    expected = await fixture_adapter(cloud).aggregate(request_, scope=scope)
    assert compare_results(expected, await adapter.aggregate(request_, scope=scope)) == []
    nulls = await adapter.aggregate(
        make_request(Metric.OUTPUT_TOKENS, Aggregation.MAX, group_by=(Dimension.MODEL,)),
        scope=make_scope(cloud),
    )
    legacy = next(r for r in nulls.rows if r.keys == ("embed-legacy",))
    assert legacy.value is None and legacy.unknown_count == legacy.row_count


@pytest.mark.parametrize("mode", MODES)
async def test_quantile_refused_before_any_statement_is_sent(mode: str) -> None:
    adapter, recording, _ = build(mode)
    quantile = make_request(Metric.DURATION_MS, Aggregation.APPROX_QUANTILE, quantile=0.95)
    with pytest.raises(CapabilityUnavailableError):
        await adapter.aggregate(quantile, scope=make_scope())
    assert recording.statements == []


# --- mode selection and statement shape ------------------------------------------------------


async def test_mode_changes_the_emitted_sql_and_values_are_bound() -> None:
    from neurosphere_core.analytics.base import FilterClause, FilterOp

    usd = FilterClause(field=Dimension.CURRENCY, op=FilterOp.EQ, values=("USD",))
    request_ = make_request(
        Metric.COST_AMOUNT, Aggregation.SUM, filters=(usd,), group_by=(Dimension.MODEL,)
    )
    sql: dict[str, str] = {}
    for mode in MODES:
        adapter, recording, _ = build(mode)
        assert adapter.mode == mode
        await adapter.aggregate(request_, scope=make_scope())
        statement = recording.statements[-1]
        sql[mode] = statement.sql
        assert statement.sql.startswith("SELECT TOP 1001 ")
        assert "[ns].[ns_analytics_events]" in statement.sql
        assert "USD" not in statement.sql and "contoso" not in statement.sql
        assert "USD" in statement.params
        assert statement.sql.count("?") == len(statement.params)
    assert "OPTION (LABEL = 'ns_analytics')" in sql["dedicated"]
    assert "OPTION" not in sql["serverless"]
    assert sql["dedicated"] != sql["serverless"]


async def test_time_bucket_uses_dateadd_datediff() -> None:
    adapter, recording, _ = build("serverless")
    await adapter.aggregate(make_request(time_bucket=Granularity.HOUR), scope=make_scope())
    assert "DATEADD(hour, DATEDIFF(hour, 0, [event_time]), 0)" in recording.statements[-1].sql


# --- cloud / host / mode boundary ------------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("cloud", get_args(Cloud))
def test_canonical_and_explicit_hosts_are_accepted(mode: str, cloud: Cloud) -> None:
    mark = "-ondemand" if mode == "serverless" else ""
    host = f"nsdemo{mark}{SUFFIX[cloud]}"
    explicit, _, _ = build(mode, cloud, host=host)
    derived, _, _ = build(mode, cloud)
    assert explicit.endpoint_host == derived.endpoint_host == host
    assert explicit.cloud == cloud


@pytest.mark.parametrize(
    ("cloud", "host", "mode"),
    [
        ("government", "nsdemo-ondemand.sql.azuresynapse.net", "serverless"),
        ("government", "nsdemo.sql.azuresynapse.net", "dedicated"),
        ("commercial", "nsdemo-ondemand.sql.azuresynapse.usgovcloudapi.net", "serverless"),
        ("commercial", "nsdemo.sql.azuresynapse.usgovcloudapi.net", "dedicated"),
        ("commercial", "nsdemo.database.windows.net", "dedicated"),
        ("government", "nsdemo.database.usgovcloudapi.net", "dedicated"),
        ("commercial", "other-ondemand.sql.azuresynapse.net", "serverless"),  # wrong workspace
        ("commercial", "NSDEMO.sql.azuresynapse.net", "dedicated"),
        ("commercial", "nsdemo.sql.azuresynapse.net.evil.example", "dedicated"),
    ],
)
def test_host_cloud_mismatch_fails_at_construction(cloud: str, host: str, mode: str) -> None:
    with pytest.raises(InvalidSchemaError):
        synapse.create_adapter(
            cloud=cloud,
            region=REGION[cloud],
            config=make_config(mode, host=host),
            executor=object(),
        )


@pytest.mark.parametrize(
    ("mode", "host"),
    [
        ("dedicated", "nsdemo-ondemand.sql.azuresynapse.net"),
        ("serverless", "nsdemo.sql.azuresynapse.net"),
    ],
)
def test_host_mode_mismatch_fails_at_construction(mode: str, host: str) -> None:
    with pytest.raises(InvalidSchemaError) as err:
        synapse.create_adapter(
            cloud="commercial",
            region="eastus",
            config=make_config(mode, host=host),
            executor=object(),
        )
    assert "mode" in str(err.value) or "host" in str(err.value)


def test_region_must_match_cloud() -> None:
    for cloud, region in (("government", "eastus"), ("commercial", "usgovvirginia")):
        with pytest.raises(InvalidSchemaError):
            synapse.create_adapter(
                cloud=cloud, region=region, config=make_config("dedicated"), executor=object()
            )


def test_config_is_frozen_forbids_secrets_and_never_echoes_values() -> None:
    config = SynapseConfig.model_validate(make_config("dedicated"))
    with pytest.raises(Exception, match="frozen"):
        config.mode = "serverless"  # type: ignore[misc]
    leaked = "hunter2-do-not-log"
    for extra in ({"password": leaked}, {"connection_string": leaked}, {"auth": leaked}):
        with pytest.raises(InvalidSchemaError) as err:
            synapse.create_adapter(
                cloud="commercial",
                region="eastus",
                config=make_config("dedicated", **extra),
                executor=object(),
            )
        assert leaked not in str(err.value) and leaked not in repr(err.value.detail)
    with pytest.raises(InvalidSchemaError):  # dedicated has no external data source
        synapse.create_adapter(
            cloud="commercial",
            region="eastus",
            config=make_config("dedicated", external_data_source="x"),
            executor=object(),
        )


def test_executor_is_required_and_cloud_is_closed() -> None:
    with pytest.raises(InvalidSchemaError):
        synapse.create_adapter(
            cloud="commercial", region="eastus", config=make_config("dedicated"), executor=None
        )
    with pytest.raises(InvalidSchemaError):
        synapse.create_adapter(
            cloud="china", region="eastus", config=make_config("dedicated"), executor=object()
        )


def test_registry_builds_synapse_for_the_requested_cloud() -> None:
    endpoint = StubSqlEndpoint((), shims=synapse_stub_shims(), schema="ns")
    adapter = registry_create(
        "synapse",
        cloud="commercial",
        region="eastus",
        config=make_config("serverless"),
        executor=endpoint,
    )
    assert adapter.cloud == "commercial" and adapter.backend == "synapse-serverless"


# --- budget ----------------------------------------------------------------------------------


class SlowExecutor:
    cancelled = False

    async def execute(self, statement: Statement, *, limits: ExecutionLimits) -> ExecutionOutcome:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        raise AssertionError("unreachable")  # pragma: no cover


async def test_budget_timeout_is_enforced_through_the_adapter() -> None:
    slow = SlowExecutor()
    adapter = synapse.create_adapter(
        cloud="commercial", region="eastus", config=make_config("dedicated"), executor=slow
    )
    with pytest.raises(RateLimitedError) as err:
        await adapter.aggregate(make_request(budget=make_budget(timeout_ms=50)), scope=make_scope())
    assert err.value.reason == "time_budget_exceeded" and slow.cancelled


async def test_rows_scanned_budget_is_enforced_through_the_adapter() -> None:
    adapter, _, _ = build("dedicated")
    with pytest.raises(RateLimitedError) as err:
        await adapter.aggregate(
            make_request(budget=make_budget(max_rows_scanned=5)), scope=make_scope()
        )
    assert err.value.reason == "rows_scanned_budget_exceeded"


# --- migrations ------------------------------------------------------------------------------


class SqliteMigrationExecutor:
    """MigrationExecutor over SQLite with the declared DDL shims; counts DDL and ledger writes."""

    def __init__(self, records: tuple[AnalyticsRecord, ...]) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("ATTACH DATABASE ':memory:' AS ns")
        # Fixture snapshot standing in for the Parquet files serverless reads through OPENROWSET.
        self.conn.execute(
            "CREATE TABLE ns.lake_events (event_id TEXT, event_time TEXT, cloud TEXT, "
            "customer_id TEXT, domain_id TEXT, provider TEXT, model TEXT, span_kind TEXT, "
            "outcome TEXT, currency TEXT, duration_ms INT, input_tokens INT, output_tokens INT, "
            "cost_amount TEXT)"
        )
        self.conn.executemany(
            "INSERT INTO ns.lake_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    r.event_id, r.event_time.isoformat(), r.cloud, r.customer_id, r.domain_id,
                    r.provider, r.model, r.span_kind, r.outcome, r.currency, r.duration_ms,
                    r.input_tokens, r.output_tokens,
                    None if r.cost_amount is None else format(r.cost_amount, "f"),
                )
                for r in records
            ],
        )  # fmt: skip
        self.rules = tsql_ddl_shim().rules
        self.sent: list[str] = []

    async def run(self, sql: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
        self.sent.append(sql)
        for rule in self.rules:
            sql = re.sub(rule.pattern, rule.replacement, sql)
        if params:
            return [tuple(r) for r in self.conn.execute(sql, params).fetchall()]
        if sql.lstrip().upper().startswith("SELECT"):
            return [tuple(r) for r in self.conn.execute(sql).fetchall()]
        self.conn.executescript(sql)
        return []

    def ledger(self) -> list[tuple[Any, ...]]:
        return self.conn.execute(
            f"SELECT version, name FROM ns.{LEDGER_TABLE} ORDER BY version"
        ).fetchall()

    def objects(self) -> set[str]:
        rows = self.conn.execute("SELECT name FROM ns.sqlite_master").fetchall()
        return {r[0] for r in rows}


@pytest.mark.parametrize("mode", MODES)
async def test_migrations_are_versioned_applied_once_and_idempotent(mode: str) -> None:
    config = SynapseConfig.model_validate(make_config(mode))
    expected = migrations_for(config)
    assert [m.id[:5] for m in expected] == [f"V{i:03d}_" for i in range(1, len(expected) + 1)]
    assert all(re.fullmatch(r"V\d{3}__[a-z_]+", m.id) for m in expected)
    executor = SqliteMigrationExecutor(build_dataset("commercial"))

    first = await synapse.apply_migrations(executor, config)
    assert first == tuple(m.id for m in expected)
    assert "ns_analytics_events" in executor.objects()
    assert executor.ledger() == [(m.version, m.name) for m in expected]
    count = executor.conn.execute('SELECT COUNT(*) FROM ns."ns_analytics_events"').fetchone()[0]
    # serverless: the view reads the snapshot; dedicated: a new, empty table
    assert count == (len(build_dataset("commercial")) if mode == "serverless" else 0)

    sent_before = len(executor.sent)
    second = await synapse.apply_migrations(executor, config)
    assert second == ()
    migration_sql = {s for m in expected for s in m.statements}
    assert not migration_sql & set(executor.sent[sent_before:])  # no DDL re-run
    assert executor.ledger() == [(m.version, m.name) for m in expected]


async def test_modes_use_tables_versus_views_and_differ() -> None:
    dedicated = migrations_for(SynapseConfig.model_validate(make_config("dedicated")))
    serverless = migrations_for(SynapseConfig.model_validate(make_config("serverless")))
    assert "CREATE TABLE" in dedicated[0].statements[0]
    assert "DISTRIBUTION = ROUND_ROBIN" in dedicated[0].statements[0]
    assert "CREATE OR ALTER VIEW" in serverless[0].statements[0]
    assert "OPENROWSET" in serverless[0].statements[0]
    assert not any("CREATE TABLE" in s for m in serverless for s in m.statements)
    assert dedicated[0].checksum != serverless[0].checksum


async def test_serverless_needs_a_data_source_and_drift_is_detected() -> None:
    bare = SynapseConfig.model_validate(
        {"mode": "serverless", "workspace": "nsdemo", "database": "nsanalytics"}
    )
    with pytest.raises(MigrationError):
        migrations_for(bare)
    config = SynapseConfig.model_validate(make_config("dedicated"))
    executor = SqliteMigrationExecutor(())
    await synapse.apply_migrations(executor, config)
    executor.conn.execute(f"UPDATE ns.{LEDGER_TABLE} SET checksum = 'edited' WHERE version = 1")
    with pytest.raises(MigrationError, match="drift"):
        await synapse.apply_migrations(executor, config)


def test_g12_gaps_are_documented() -> None:
    text = " ".join(synapse.G12_PARITY_GAPS).lower()
    for needle in ("top", "quantile", "dwu", "throttl", "entra", "cold start"):
        assert needle in text or needle.replace("throttl", "concurrency") in text
