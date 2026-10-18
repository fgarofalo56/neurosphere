"""Shared builders for the analytics tests (synthetic data only)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.analytics.base import (
    AggregateRequest,
    Aggregation,
    AnalyticsBudget,
    AnalyticsRecord,
    AnsiDialect,
    Metric,
    SqlAnalytics,
    StubSqlEndpoint,
    TimeRange,
    standard_shims,
)
from neurosphere_core.analytics.fixture import FixtureAnalytics, build_dataset, domain_id
from neurosphere_core.scope import IdentityScope

START = datetime(2026, 10, 1, tzinfo=UTC)
END = datetime(2026, 10, 15, tzinfo=UTC)
TIME_RANGE = TimeRange(start=START, end=END)


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


def make_budget(
    *,
    timeout_ms: int = 5000,
    limit: int = 1000,
    max_rows_scanned: int = 1_000_000,
    max_cost_units: str = "1000",
) -> AnalyticsBudget:
    return AnalyticsBudget(
        query=Budget(timeout_ms=timeout_ms, limit=limit, max_depth=0),
        max_rows_scanned=max_rows_scanned,
        max_cost_units=Decimal(max_cost_units),
    )


def make_request(
    metric: Metric = Metric.EVENTS,
    aggregation: Aggregation = Aggregation.COUNT,
    *,
    budget: AnalyticsBudget | None = None,
    **extra: Any,
) -> AggregateRequest:
    return AggregateRequest(
        metric=metric,
        aggregation=aggregation,
        time_range=TIME_RANGE,
        budget=budget or make_budget(),
        **extra,
    )


def fixture_adapter(cloud: str = "commercial", **kwargs: Any) -> FixtureAnalytics:
    return FixtureAnalytics(build_dataset(cloud), cloud=cloud, sandbox=True, **kwargs)  # type: ignore[arg-type]


def stub_adapter(
    records: tuple[AnalyticsRecord, ...], cloud: str = "commercial", **kwargs: Any
) -> tuple[SqlAnalytics, StubSqlEndpoint]:
    endpoint = StubSqlEndpoint(records, shims=standard_shims(), **kwargs)
    return (
        SqlAnalytics(backend="stub-ansi", cloud=cloud, dialect=AnsiDialect(), executor=endpoint),  # type: ignore[arg-type]
        endpoint,
    )
