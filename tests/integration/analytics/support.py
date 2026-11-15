"""Shared builders for the analytics equivalence and gating suites (synthetic data only)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from neurosphere_core.analytics.base import (
    AnalyticsAdapter,
    Cloud,
    StubSqlEndpoint,
)
from neurosphere_core.analytics.base import create_adapter as registry_create
from neurosphere_core.analytics.databricks import DatabricksConfig, sqlite_shims
from neurosphere_core.analytics.fabric import fabric_stub_shims
from neurosphere_core.analytics.fixture import (
    TIME_RANGE,
    FixtureAnalytics,
    build_dataset,
    make_request,
    make_scope,
)
from neurosphere_core.analytics.synapse.stub_shims import synapse_stub_shims

REGION: dict[str, str] = {"commercial": "eastus2", "government": "usgovvirginia"}
FABRIC_HOST: dict[str, str] = {
    "commercial": "abc123.datawarehouse.fabric.microsoft.com",
    "government": "abc123.fabric.microsoft.us",
}
DBX_HOST: dict[str, str] = {
    "commercial": "adb-1234567890123456.7.azuredatabricks.net",
    "government": "adb-1234567890123456.7.databricks.azure.us",
}
ADAPTERS = ("fabric", "synapse-serverless", "synapse-dedicated", "databricks")


def fixture_adapter(cloud: Cloud) -> FixtureAnalytics:
    return FixtureAnalytics(build_dataset(cloud), cloud=cloud, sandbox=True)


@dataclass(frozen=True)
class Built:
    adapter: AnalyticsAdapter
    endpoint: StubSqlEndpoint


def build_adapter(kind: str, cloud: Cloud, region: str | None = None) -> Built:
    """One adapter built through its real config and the registry over a stub endpoint."""
    region = region or REGION[cloud]
    records = build_dataset(cloud)
    if kind == "fabric":
        endpoint = StubSqlEndpoint(records, shims=fabric_stub_shims(), schema="dbo")
        config: dict[str, Any] = {"sql_endpoint_host": FABRIC_HOST[cloud], "database": "ns"}
        adapter = registry_create(
            "fabric", cloud=cloud, region=region, config=config, executor=endpoint
        )
        return Built(adapter, endpoint)
    if kind.startswith("synapse-"):
        mode = kind.split("-", 1)[1]
        endpoint = StubSqlEndpoint(records, shims=synapse_stub_shims(), schema="ns")
        config = {"mode": mode, "workspace": "nsdemo", "database": "nsanalytics"}
        if mode == "serverless":
            config["external_data_source"] = "ns_lake"
        adapter = registry_create(
            "synapse", cloud=cloud, region=region, config=config, executor=endpoint
        )
        return Built(adapter, endpoint)
    assert kind == "databricks"
    dbx = DatabricksConfig.model_validate(
        {
            "cloud": cloud,
            "region": region,
            "workspace_host": DBX_HOST[cloud],
            "warehouse_id": "0123456789abcdef",
            "catalog": "neurosphere",
            "schema_name": "analytics",
        }
    )
    endpoint = StubSqlEndpoint(records, shims=sqlite_shims(dbx), schema=dbx.schema_name)
    adapter = registry_create(
        "databricks",
        cloud=cloud,
        region=region,
        config=dbx.model_dump(mode="json"),
        executor=endpoint,
    )
    return Built(adapter, endpoint)


# Re-exported for the suite and the live script (the product module owns the workload).
__all__ = [
    "ADAPTERS",
    "DBX_HOST",
    "FABRIC_HOST",
    "REGION",
    "TIME_RANGE",
    "build_adapter",
    "fixture_adapter",
    "make_request",
    "make_scope",
]
