"""Shared builders for the analytics equivalence and gating suites (synthetic data only)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.analytics.base import (
    AggregateRequest,
    Aggregation,
    AnalyticsAdapter,
    AnalyticsBudget,
    Cloud,
    Metric,
    StubSqlEndpoint,
    TimeRange,
)
from neurosphere_core.analytics.base import create_adapter as registry_create
from neurosphere_core.analytics.databricks import DatabricksConfig, sqlite_shims
from neurosphere_core.analytics.fabric import fabric_stub_shims
from neurosphere_core.analytics.fixture import FixtureAnalytics, build_dataset, domain_id
from neurosphere_core.analytics.synapse.stub_shims import synapse_stub_shims
from neurosphere_core.scope import IdentityScope

TIME_RANGE = TimeRange(
    start=datetime(2026, 10, 1, tzinfo=UTC), end=datetime(2026, 10, 15, tzinfo=UTC)
)

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


def make_scope(
    cloud: str = "commercial",
    customer: str = "contoso",
    domains: tuple[str, ...] = ("retail", "finance", "support"),
) -> IdentityScope:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": cloud,
            "customer_id": customer,
            "principal": {
                "principal_id": f"{cloud}:{customer}:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": "p-7f3a9c21",
                "principal_kind": "user",
            },
            "roles": [],
            "allowed_domains": [domain_id(cloud, customer, d) for d in domains],  # type: ignore[arg-type]
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-10T00:00:00Z",
            "scope_hash": "sha256:" + hashlib.sha256(b"scope").hexdigest(),
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


def make_request(
    metric: Metric = Metric.EVENTS,
    aggregation: Aggregation = Aggregation.COUNT,
    **extra: Any,
) -> AggregateRequest:
    return AggregateRequest(
        metric=metric,
        aggregation=aggregation,
        time_range=TIME_RANGE,
        budget=AnalyticsBudget(
            query=Budget(timeout_ms=5000, limit=1000, max_depth=0),
            max_rows_scanned=1_000_000,
            max_cost_units=Decimal("1000"),
        ),
        **extra,
    )


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
