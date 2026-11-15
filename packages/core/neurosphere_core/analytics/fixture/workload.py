"""The shared equivalence workload (PRP-11 round 2, item 1; issue #60 bullet 2).

One product-side source for the request set and the synthetic scope, imported by the
equivalence suite and by ``scripts/gates/g01_analytics_live.py``. Synthetic data only.
"""

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
    Dimension,
    FilterClause,
    FilterOp,
    Granularity,
    Metric,
    TimeRange,
)
from neurosphere_core.analytics.fixture.data import domain_id
from neurosphere_core.scope import IdentityScope

TIME_RANGE = TimeRange(
    start=datetime(2026, 10, 1, tzinfo=UTC), end=datetime(2026, 10, 15, tzinfo=UTC)
)
USD = FilterClause(field=Dimension.CURRENCY, op=FilterOp.EQ, values=("USD",))


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


def _domain_filter(cloud: str) -> FilterClause:
    return FilterClause(
        field=Dimension.DOMAIN_ID,
        op=FilterOp.IN,
        values=(domain_id(cloud, "contoso", "retail"), domain_id(cloud, "contoso", "finance")),  # type: ignore[arg-type]
    )


def equivalence_cases(cloud: str) -> list[tuple[str, AggregateRequest]]:
    """The named request set every adapter must answer like the fixture oracle."""
    return [
        ("count", make_request()),
        ("count-by-model-outcome", make_request(group_by=(Dimension.MODEL, Dimension.OUTCOME))),
        (
            "count-day-provider",
            make_request(time_bucket=Granularity.DAY, group_by=(Dimension.PROVIDER,)),
        ),
        ("count-hour", make_request(time_bucket=Granularity.HOUR)),
        (
            "sum-tokens-by-domain",
            make_request(Metric.INPUT_TOKENS, Aggregation.SUM, group_by=(Dimension.DOMAIN_ID,)),
        ),
        (
            "sum-cost-usd-by-model",
            make_request(
                Metric.COST_AMOUNT, Aggregation.SUM, filters=(USD,), group_by=(Dimension.MODEL,)
            ),
        ),
        (
            "sum-cost-by-currency",
            make_request(Metric.COST_AMOUNT, Aggregation.SUM, group_by=(Dimension.CURRENCY,)),
        ),
        (
            "min-duration",
            make_request(Metric.DURATION_MS, Aggregation.MIN, group_by=(Dimension.MODEL,)),
        ),
        (
            "max-duration-by-kind",
            make_request(Metric.DURATION_MS, Aggregation.MAX, group_by=(Dimension.SPAN_KIND,)),
        ),
        (
            "all-null-group-max-output",
            make_request(Metric.OUTPUT_TOKENS, Aggregation.MAX, group_by=(Dimension.MODEL,)),
        ),
        (
            "domain-narrowing-filter",
            make_request(group_by=(Dimension.DOMAIN_ID,), filters=(_domain_filter(cloud),)),
        ),
        (
            "filter-in-and-unknown",
            make_request(
                group_by=(Dimension.OUTCOME,),
                filters=(
                    FilterClause(
                        field=Dimension.PROVIDER,
                        op=FilterOp.IN,
                        values=("azure_openai", "anthropic"),
                    ),
                    FilterClause(field=Dimension.SPAN_KIND, op=FilterOp.IS_UNKNOWN),
                ),
            ),
        ),
        (
            "p95-duration",
            make_request(
                Metric.DURATION_MS,
                Aggregation.APPROX_QUANTILE,
                quantile=0.95,
                group_by=(Dimension.MODEL,),
            ),
        ),
        (
            "p50-cost-usd",
            make_request(
                Metric.COST_AMOUNT,
                Aggregation.APPROX_QUANTILE,
                quantile=0.5,
                filters=(USD,),
                group_by=(Dimension.DOMAIN_ID,),
            ),
        ),
    ]
