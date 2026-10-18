"""Databricks adapter: equivalence to the fixture over the stub, dialect shape, cloud boundary,
credential hygiene, migrations and budgets. Contract conformance only (see ``stub.py``)."""

from __future__ import annotations

import logging
import re
import sqlite3
from decimal import Decimal
from typing import Any

import pytest
from neurosphere_contracts.connectors.v1.connector_manifest import CredentialRef
from neurosphere_core.analytics.base import (
    RETRY_AFTER_SECONDS,
    Cloud,
    StubSqlEndpoint,
    compare_results,
)
from neurosphere_core.analytics.base.dialect import Statement
from neurosphere_core.analytics.base.enforcement import ExecutionLimits, ExecutionOutcome
from neurosphere_core.analytics.base.registry import create_adapter as registry_create
from neurosphere_core.analytics.databricks import (
    G12_PARITY_GAPS,
    MIGRATIONS,
    SQLITE_MIGRATION_REWRITES,
    DatabricksAnalytics,
    DatabricksConfig,
    DatabricksDialect,
    apply_migrations,
    create_adapter,
    sqlite_shims,
)
from neurosphere_core.analytics.fixture import build_dataset
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    InvalidSchemaError,
    RateLimitedError,
)
from pydantic import ValidationError

from .analytics_helpers import fixture_adapter, make_request, make_scope
from .test_fixture_equivalence import CASES

VAULT = "https://nsvault01.vault.azure.net/secrets/dbx-sp-secret"
GOV_VAULT = "https://nsvault01.vault.usgovcloudapi.net/secrets/dbx-sp-secret"
CLIENT = "11111111-2222-3333-4444-555555555555"


def config_for(cloud: Cloud = "commercial", **over: Any) -> DatabricksConfig:
    base: dict[str, Any] = {
        "cloud": cloud,
        "region": "eastus" if cloud == "commercial" else "usgovvirginia",
        "workspace_host": (
            "adb-1234567890123456.7.azuredatabricks.net"
            if cloud == "commercial"
            else "adb-1234567890123456.7.databricks.azure.us"
        ),
        "warehouse_id": "0123456789abcdef",
        "catalog": "neurosphere",
        "schema_name": "analytics",
    }
    base.update(over)
    return DatabricksConfig.model_validate(base)


def adapter_and_endpoint(
    cloud: Cloud = "commercial",
) -> tuple[DatabricksAnalytics, StubSqlEndpoint]:
    config = config_for(cloud)
    endpoint = StubSqlEndpoint(
        build_dataset(cloud), shims=sqlite_shims(config), schema=config.schema_name
    )
    return DatabricksAnalytics(config, executor=endpoint), endpoint


@pytest.mark.parametrize(("name", "request_"), CASES, ids=[c[0] for c in CASES])
@pytest.mark.parametrize("cloud", ["commercial", "government"])
async def test_databricks_equals_fixture(name: str, request_: Any, cloud: Cloud) -> None:
    adapter, endpoint = adapter_and_endpoint(cloud)
    scope = make_scope(cloud)
    expected = await fixture_adapter(cloud).aggregate(request_, scope=scope)
    actual = await adapter.aggregate(request_, scope=scope)
    assert compare_results(expected, actual) == []
    assert expected.rows
    assert actual.backend == "databricks" and actual.cloud == cloud
    assert endpoint.applied_shims


async def test_null_groups_stay_unknown() -> None:
    from neurosphere_core.analytics.base import Aggregation, Dimension, Metric

    adapter, _ = adapter_and_endpoint()
    result = await adapter.aggregate(
        make_request(Metric.OUTPUT_TOKENS, Aggregation.MAX, group_by=(Dimension.MODEL,)),
        scope=make_scope(),
    )
    legacy = next(r for r in result.rows if r.keys == ("embed-legacy",))
    assert legacy.value is None and legacy.unknown_count == legacy.row_count


class Recorder:
    def __init__(self) -> None:
        self.statements: list[Statement] = []

    async def execute(self, statement: Statement, *, limits: ExecutionLimits) -> ExecutionOutcome:
        self.statements.append(statement)
        return ExecutionOutcome(rows=(), rows_scanned=0, cost_units=Decimal(0))


async def test_emitted_sql_is_databricks_shaped_and_bound() -> None:
    from neurosphere_core.analytics.base import (
        Aggregation,
        Dimension,
        FilterClause,
        FilterOp,
        Granularity,
        Metric,
    )

    recorder = Recorder()
    adapter = DatabricksAnalytics(config_for(), executor=recorder)  # type: ignore[arg-type]
    hostile = "azure:p9@x--DROP"
    request_ = make_request(
        Metric.DURATION_MS,
        Aggregation.APPROX_QUANTILE,
        quantile=0.95,
        time_bucket=Granularity.HOUR,
        group_by=(Dimension.MODEL,),
        filters=(FilterClause(field=Dimension.PROVIDER, op=FilterOp.EQ, values=(hostile,)),),
    )
    await adapter.aggregate(request_, scope=make_scope())
    (statement,) = recorder.statements
    sql = statement.sql
    assert "`neurosphere`.`analytics`.`ns_analytics_events`" in sql
    assert "date_trunc('HOUR', `event_time`)" in sql
    assert "percentile_approx(`duration_ms`, 0.95)" in sql
    assert re.search(r" LIMIT \d+$", sql)
    assert '"' not in sql
    markers = re.findall(r":p(\d+)", sql)
    assert markers == [str(i) for i in range(1, len(statement.params) + 1)]
    assert hostile in statement.params and hostile not in sql
    assert "?" not in sql


def test_dialect_rejects_colliding_namespace() -> None:
    with pytest.raises(ValueError, match="collide"):
        DatabricksDialect(catalog="neurosphere", schema="model")


# --- cloud boundary -------------------------------------------------------------------------


def test_host_cloud_mismatch_rejected_both_directions() -> None:
    with pytest.raises(ValidationError):
        config_for("government", workspace_host="adb-1234567890123456.7.azuredatabricks.net")
    with pytest.raises(ValidationError):
        config_for("commercial", workspace_host="adb-1234567890123456.7.databricks.azure.us")


@pytest.mark.parametrize(
    "host",
    [
        "evil.example.com",
        "adb-1.7.azuredatabricks.net.evil.com",
        "https://adb-1.7.azuredatabricks.net",
        "ADB-1.7.azuredatabricks.net",
        "adb-1.7.azuredatabricks.net/",
    ],
)
def test_malformed_hosts_rejected(host: str) -> None:
    with pytest.raises(ValidationError):
        config_for(workspace_host=host)


def test_region_must_match_cloud() -> None:
    with pytest.raises(ValidationError):
        config_for("government", region="eastus")
    with pytest.raises(ValidationError):
        config_for("commercial", region="usgovvirginia")
    assert config_for("government", region="usgovarizona").region == "usgovarizona"


@pytest.mark.parametrize(
    "over",
    [
        {"catalog": "x`; DROP"},
        {"schema_name": "a.b"},
        {"warehouse_id": "../../etc"},
        {"warehouse_id": "0123456789ABCDEF"},
    ],
)
def test_identifiers_are_regex_checked(over: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        config_for(**over)


def test_factory_cloud_mismatch_fails_at_construction() -> None:
    config = {
        "workspace_host": "adb-1234567890123456.7.azuredatabricks.net",
        "warehouse_id": "0123456789abcdef",
        "catalog": "c",
        "schema_name": "s",
    }
    with pytest.raises(InvalidSchemaError) as err:
        create_adapter(cloud="government", region="usgovvirginia", config=config, executor=object())
    assert err.value.reason == "databricks_config"
    with pytest.raises(InvalidSchemaError):
        create_adapter(cloud="commercial", region="eastus", config=config, executor=None)
    with pytest.raises(InvalidSchemaError):
        create_adapter(
            cloud="commercial",
            region="eastus",
            config={**config, "cloud": "government"},
            executor=object(),
        )


def test_factory_builds_adapter_with_requested_cloud() -> None:
    adapter = create_adapter(
        cloud="government",
        region="usgovarizona",
        config={
            "workspace_host": "adb-9.1.databricks.azure.us",
            "warehouse_id": "0123456789abcdef",
            "catalog": "c",
            "schema_name": "s",
        },
        executor=Recorder(),
    )
    assert adapter.cloud == "government" and adapter.backend == "databricks"


def test_registry_builds_government_and_gates_unlisted_regions() -> None:
    cfg = {
        "workspace_host": "adb-9.1.databricks.azure.us",
        "warehouse_id": "0123456789abcdef",
        "catalog": "c",
        "schema_name": "s",
    }
    adapter = registry_create(
        "databricks", cloud="government", region="usgovvirginia", config=cfg, executor=Recorder()
    )
    assert adapter.cloud == "government"
    with pytest.raises(CapabilityUnavailableError):
        registry_create(
            "databricks", cloud="government", region="usgovtexas", config=cfg, executor=Recorder()
        )


# --- credentials ----------------------------------------------------------------------------


def test_no_raw_secret_fields_and_extra_forbidden() -> None:
    for forbidden in ("token", "access_token", "password", "client_secret", "pat"):
        with pytest.raises(ValidationError):
            extra: dict[str, Any] = {forbidden: "dapi-super-secret-value"}
            config_for(**extra)
    assert not {"token", "password", "secret"} & set(DatabricksConfig.model_fields)


def test_service_principal_needs_vault_reference_only() -> None:
    with pytest.raises(ValidationError):
        config_for(auth_mode="service_principal")
    with pytest.raises(ValidationError):
        config_for(auth_mode="service_principal", client_id=CLIENT, credential="plain-secret")
    with pytest.raises(ValidationError):
        config_for(
            auth_mode="service_principal",
            client_id=CLIENT,
            credential={"name": "sp_secret", "vault_ref": "https://evil.example.com/secrets/x"},
        )
    with pytest.raises(ValidationError):
        config_for(credential={"name": "sp_secret", "vault_ref": VAULT})  # managed identity
    ok = config_for(
        auth_mode="service_principal",
        client_id=CLIENT,
        credential=CredentialRef(name="sp_secret", vault_ref=VAULT),
    )
    assert ok.credential is not None and ok.credential.vault_ref == VAULT


def test_credentials_absent_from_repr_logs_and_errors(caplog: pytest.LogCaptureFixture) -> None:
    canary = "SENTINEL-leak-canary-value"
    caplog.set_level(logging.DEBUG)
    with pytest.raises(ValidationError) as err:
        config_for(auth_mode="service_principal", client_id=CLIENT, token=canary)
    with pytest.raises(InvalidSchemaError) as wrapped:
        create_adapter(
            cloud="commercial",
            region="eastus",
            config={"workspace_host": "adb-1.7.azuredatabricks.net", "token": canary},
            executor=object(),
        )
    config = config_for(
        auth_mode="service_principal",
        client_id=CLIENT,
        credential={"name": "sp_secret", "vault_ref": VAULT},
    )
    adapter = DatabricksAnalytics(config, executor=Recorder())  # type: ignore[arg-type]
    assert VAULT not in repr(config) and VAULT not in repr(adapter) and VAULT not in str(adapter)
    assert canary not in wrapped.value.detail  # type: ignore[operator]
    del err  # pydantic's own error echoes input by design; the adapter wrapper must not
    assert canary not in caplog.text and canary not in repr(wrapped.value)


def test_government_vault_reference_is_a_valid_ref() -> None:
    cfg = config_for(
        "government",
        auth_mode="service_principal",
        client_id=CLIENT,
        credential={"name": "sp_secret", "vault_ref": GOV_VAULT},
    )
    assert cfg.credential is not None


# --- migrations -----------------------------------------------------------------------------


class SqliteMigrationExecutor:
    """Runs migration statements on SQLite after the adapter's declared rewrites (test-only)."""

    def __init__(self, schema: str) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(f"ATTACH DATABASE ':memory:' AS \"{schema}\"")
        self.log: list[str] = []

    async def execute(self, statement: Statement, *, limits: ExecutionLimits) -> ExecutionOutcome:
        sql = statement.sql
        for rule in SQLITE_MIGRATION_REWRITES:
            sql = re.sub(rule.pattern, rule.replacement, sql)
        self.log.append(sql)
        rows = self.conn.execute(sql, statement.params).fetchall()
        self.conn.commit()
        return ExecutionOutcome(
            rows=tuple(tuple(r) for r in rows), rows_scanned=0, cost_units=Decimal(0)
        )


async def test_migrations_versioned_and_idempotent() -> None:
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions) and all(re.fullmatch(r"V\d{3}", v) for v in versions)
    executor = SqliteMigrationExecutor("analytics")
    first = await apply_migrations(executor, catalog="neurosphere", schema="analytics")  # type: ignore[arg-type]
    assert first == tuple(versions)
    snapshot = executor.conn.execute('SELECT * FROM "analytics"."ns_schema_version"').fetchall()
    columns = [
        r[1] for r in executor.conn.execute('PRAGMA analytics.table_info("ns_analytics_events")')
    ]
    assert "trace_id" in columns and "event_id" in columns
    statements_after_first = len(executor.log)
    second = await apply_migrations(executor, catalog="neurosphere", schema="analytics")  # type: ignore[arg-type]
    assert second == ()
    assert (
        executor.conn.execute('SELECT * FROM "analytics"."ns_schema_version"').fetchall()
        == snapshot
    )
    # the second run only created-if-not-exists the ledger and read it
    assert len(executor.log) == statements_after_first + 2
    assert all(
        "IF NOT EXISTS" in s or s.startswith(("SELECT", "INSERT", "ALTER")) for s in executor.log
    )


def test_migration_sql_is_databricks_shaped() -> None:
    v1 = MIGRATIONS[0].statements("neurosphere", "analytics")[0]
    assert v1.startswith("CREATE TABLE IF NOT EXISTS `neurosphere`.`analytics`.")
    assert v1.endswith("USING DELTA")
    v2 = MIGRATIONS[1].statements("neurosphere", "analytics")[0]
    assert "ADD COLUMNS" in v2
    with pytest.raises(ValueError, match="identifier"):
        MIGRATIONS[0].statements("bad`name", "analytics")


# --- budgets and gaps -----------------------------------------------------------------------


async def test_budget_enforced_through_adapter() -> None:
    from .analytics_helpers import make_budget

    adapter, _ = adapter_and_endpoint()
    with pytest.raises(RateLimitedError) as err:
        await adapter.aggregate(
            make_request(budget=make_budget(max_rows_scanned=10)), scope=make_scope()
        )
    assert err.value.reason == "rows_scanned_budget_exceeded"
    assert err.value.retry_after_seconds == RETRY_AFTER_SECONDS


def test_g12_gaps_documented() -> None:
    text = " ".join(G12_PARITY_GAPS).lower()
    for needle in ("limit", "percentile_approx", "photon", "cold start", "polling", "entra"):
        assert needle in text
