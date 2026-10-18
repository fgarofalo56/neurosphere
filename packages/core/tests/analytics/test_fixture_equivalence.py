"""Fixture adapter == stub SQL endpoint through the shared renderer, within the tolerance helper.

This is the pattern Items 2-4 copy: the vendor Dialect + renderer + stub endpoint must agree
with the fixture on identical normalized input. It proves contract conformance only.
"""

from __future__ import annotations

import pytest
from neurosphere_core.analytics.base import (
    AggregateRequest,
    Aggregation,
    Cloud,
    Dimension,
    FilterClause,
    FilterOp,
    Granularity,
    Metric,
    compare_results,
)
from neurosphere_core.analytics.fixture import build_dataset, domain_id

from .analytics_helpers import fixture_adapter, make_request, make_scope, stub_adapter

USD = FilterClause(field=Dimension.CURRENCY, op=FilterOp.EQ, values=("USD",))
CASES: list[tuple[str, AggregateRequest]] = [
    ("events", make_request()),
    ("events-by-model", make_request(group_by=(Dimension.MODEL, Dimension.OUTCOME))),
    ("events-by-day", make_request(time_bucket=Granularity.DAY, group_by=(Dimension.PROVIDER,))),
    ("events-by-hour", make_request(time_bucket=Granularity.HOUR)),
    (
        "tokens-sum",
        make_request(Metric.INPUT_TOKENS, Aggregation.SUM, group_by=(Dimension.DOMAIN_ID,)),
    ),
    (
        "tokens-count",
        make_request(Metric.OUTPUT_TOKENS, Aggregation.COUNT, group_by=(Dimension.MODEL,)),
    ),
    (
        "duration-min",
        make_request(Metric.DURATION_MS, Aggregation.MIN, group_by=(Dimension.MODEL,)),
    ),
    (
        "duration-max",
        make_request(Metric.DURATION_MS, Aggregation.MAX, group_by=(Dimension.SPAN_KIND,)),
    ),
    (
        "duration-p95",
        make_request(
            Metric.DURATION_MS,
            Aggregation.APPROX_QUANTILE,
            quantile=0.95,
            group_by=(Dimension.MODEL,),
        ),
    ),
    (
        "cost-sum-usd",
        make_request(
            Metric.COST_AMOUNT, Aggregation.SUM, filters=(USD,), group_by=(Dimension.MODEL,)
        ),
    ),
    (
        "cost-sum-by-currency",
        make_request(Metric.COST_AMOUNT, Aggregation.SUM, group_by=(Dimension.CURRENCY,)),
    ),
    (
        "cost-min-max-p50",
        make_request(
            Metric.COST_AMOUNT,
            Aggregation.APPROX_QUANTILE,
            quantile=0.5,
            filters=(USD,),
            group_by=(Dimension.DOMAIN_ID,),
        ),
    ),
    (
        "filter-in-and-unknown",
        make_request(
            group_by=(Dimension.OUTCOME,),
            filters=(
                FilterClause(
                    field=Dimension.PROVIDER, op=FilterOp.IN, values=("azure_openai", "anthropic")
                ),
                FilterClause(field=Dimension.SPAN_KIND, op=FilterOp.IS_UNKNOWN),
            ),
        ),
    ),
]


@pytest.mark.parametrize(("name", "request_"), CASES, ids=[c[0] for c in CASES])
async def test_fixture_equals_stub(name: str, request_: AggregateRequest) -> None:
    records = build_dataset("commercial")
    fixture = fixture_adapter()
    stub, endpoint = stub_adapter(records)
    scope = make_scope()
    expected = await fixture.aggregate(request_, scope=scope)
    actual = await stub.aggregate(request_, scope=scope)
    assert compare_results(expected, actual) == []
    assert expected.rows  # the case actually exercised data
    assert actual.stats.rows_scanned == len(records)  # full scan by construction
    if request_.aggregation is Aggregation.MIN or request_.metric is Metric.COST_AMOUNT:
        assert any("decimal-cost" in n for n, _ in endpoint.applied_shims)


async def test_scope_equivalence_across_customers_and_government() -> None:
    cases: list[tuple[Cloud, str, tuple[str, ...]]] = [
        ("commercial", "fabrikam", ("finance",)),
        ("government", "contoso", ("retail", "support")),
    ]
    for cloud, customer, domains in cases:
        records = build_dataset(cloud)
        fixture = fixture_adapter(cloud)
        stub, _ = stub_adapter(records, cloud)
        scope = make_scope(cloud, customer, domains)
        request_ = make_request(group_by=(Dimension.DOMAIN_ID,))
        expected = await fixture.aggregate(request_, scope=scope)
        assert compare_results(expected, await stub.aggregate(request_, scope=scope)) == []
        assert {r.keys[0] for r in expected.rows} <= {
            domain_id(cloud, customer, d) for d in domains
        }


async def test_stub_null_groups_are_unknown() -> None:
    stub, _ = stub_adapter(build_dataset("commercial"))
    result = await stub.aggregate(
        make_request(Metric.OUTPUT_TOKENS, Aggregation.MAX, group_by=(Dimension.MODEL,)),
        scope=make_scope(),
    )
    legacy = next(r for r in result.rows if r.keys == ("embed-legacy",))
    assert legacy.value is None and legacy.unknown_count == legacy.row_count


async def test_stub_refuses_other_clouds_scope() -> None:
    from neurosphere_core.errors import ForbiddenError

    stub, _ = stub_adapter(build_dataset("commercial"))
    with pytest.raises(ForbiddenError):
        await stub.aggregate(make_request(), scope=make_scope("government"))
