from __future__ import annotations

import inspect
from decimal import Decimal

import pytest
from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_core.analytics.base import (
    AggregateRequest,
    Aggregation,
    AnalyticsBudget,
    CoUsageRequest,
    Dimension,
    FilterClause,
    FilterOp,
    Granularity,
    Metric,
    RecommendationCompute,
    TelemetryAnalytics,
)
from neurosphere_core.analytics.fixture import FixtureAnalytics, build_dataset, domain_id
from neurosphere_core.errors import ForbiddenError, RateLimitedError
from pydantic import ValidationError

from .analytics_helpers import TIME_RANGE, fixture_adapter, make_budget, make_request, make_scope


def test_protocols_are_satisfied() -> None:
    adapter = fixture_adapter()
    assert isinstance(adapter, TelemetryAnalytics)
    assert isinstance(adapter, RecommendationCompute)


async def test_scope_is_a_required_keyword() -> None:
    adapter = fixture_adapter()
    with pytest.raises(TypeError):
        await adapter.aggregate(make_request())  # type: ignore[call-arg]
    # Scope must be keyword-only: binding it positionally is rejected by the signature itself.
    with pytest.raises(TypeError):
        inspect.signature(adapter.aggregate).bind(make_request(), make_scope())
    assert inspect.signature(adapter.aggregate).parameters["scope"].kind is (
        inspect.Parameter.KEYWORD_ONLY
    )


async def test_non_scope_is_refused() -> None:
    with pytest.raises(ForbiddenError) as err:
        await fixture_adapter().aggregate(make_request(), scope="contoso")  # type: ignore[arg-type]
    assert err.value.reason == "scope_required"


async def test_scope_limits_customer_and_domains() -> None:
    adapter = fixture_adapter()
    request = make_request(group_by=(Dimension.DOMAIN_ID,))
    result = await adapter.aggregate(request, scope=make_scope(domains=("retail",)))
    keys = {row.keys[0] for row in result.rows}
    assert keys == {domain_id("commercial", "contoso", "retail")}
    full = await adapter.aggregate(request, scope=make_scope())
    assert {r.keys[0] for r in full.rows} == {
        domain_id("commercial", "contoso", d) for d in ("retail", "finance", "support")
    }
    # unattributed (null-domain) rows are never visible through a domain-scoped read
    assert None not in {r.keys[0] for r in full.rows}
    other = await adapter.aggregate(request, scope=make_scope(customer="fabrikam"))
    assert all("fabrikam" in str(r.keys[0]) for r in other.rows)


async def test_caller_filter_can_only_narrow() -> None:
    adapter = fixture_adapter()
    foreign = domain_id("commercial", "fabrikam", "retail")
    request = make_request(
        group_by=(Dimension.DOMAIN_ID,),
        filters=(FilterClause(field=Dimension.DOMAIN_ID, op=FilterOp.EQ, values=(foreign,)),),
    )
    result = await adapter.aggregate(request, scope=make_scope())
    assert result.rows == ()


async def test_empty_allowed_domains_returns_nothing() -> None:
    result = await fixture_adapter().aggregate(make_request(), scope=make_scope(domains=()))
    assert result.rows == ()
    assert result.stats.rows_scanned == 0


async def test_mismatched_cloud_scope_is_refused() -> None:
    with pytest.raises(ForbiddenError) as err:
        await fixture_adapter("commercial").aggregate(
            make_request(), scope=make_scope(cloud="government")
        )
    assert err.value.reason == "cloud_mismatch"


def test_dataset_never_mixes_clouds() -> None:
    with pytest.raises(ValueError, match="another cloud"):
        FixtureAnalytics(build_dataset("government", 10), cloud="commercial", sandbox=True)
    assert {r.cloud for r in build_dataset("government", 50)} == {"government"}


async def test_unknown_is_null_never_zero() -> None:
    adapter = fixture_adapter()
    result = await adapter.aggregate(
        make_request(
            Metric.DURATION_MS,
            Aggregation.SUM,
            group_by=(Dimension.MODEL,),
            filters=(
                FilterClause(field=Dimension.MODEL, op=FilterOp.EQ, values=("embed-legacy",)),
            ),
        ),
        scope=make_scope(),
    )
    (row,) = result.rows
    assert row.value is None  # every duration in this group is unknown
    assert row.unknown_count == row.row_count > 0
    # count counts known values (a real 0 here), and every aggregation reports unknown as None
    for agg in (Aggregation.MIN, Aggregation.MAX):
        r = await adapter.aggregate(
            make_request(
                Metric.INPUT_TOKENS,
                agg,
                group_by=(Dimension.MODEL,),
                filters=(
                    FilterClause(field=Dimension.MODEL, op=FilterOp.EQ, values=("embed-legacy",)),
                ),
            ),
            scope=make_scope(),
        )
        assert r.rows[0].value is None


async def test_events_count_counts_rows_and_sums_are_decimal() -> None:
    adapter = fixture_adapter()
    scope = make_scope()
    counted = await adapter.aggregate(make_request(), scope=scope)
    (row,) = counted.rows
    assert row.value == row.row_count > 0
    assert row.unknown_count == 0
    money = await adapter.aggregate(
        make_request(Metric.COST_AMOUNT, Aggregation.SUM, group_by=(Dimension.CURRENCY,)),
        scope=scope,
    )
    assert all(isinstance(r.value, Decimal) for r in money.rows)
    assert {r.keys[0] for r in money.rows} == {"USD", "EUR"}


async def test_time_bucket_and_quantile() -> None:
    adapter = fixture_adapter()
    result = await adapter.aggregate(
        make_request(
            Metric.DURATION_MS,
            Aggregation.APPROX_QUANTILE,
            quantile=0.5,
            time_bucket=Granularity.DAY,
        ),
        scope=make_scope(),
    )
    assert len(result.rows) >= 2
    assert all(r.bucket is not None and r.bucket.hour == 0 for r in result.rows)
    assert all(r.value is not None for r in result.rows)


async def test_co_usage_candidates_are_marked_candidates() -> None:
    adapter = fixture_adapter()
    request = CoUsageRequest(time_range=TIME_RANGE, budget=make_budget(), min_shared_domains=2)
    result = await adapter.co_usage_candidates(request, scope=make_scope())
    assert result.candidates
    assert all(c.status == "candidate" and c.entity_a < c.entity_b for c in result.candidates)
    assert all(c.shared_domains >= 2 for c in result.candidates)
    allowed = {domain_id("commercial", "contoso", d) for d in ("retail", "finance", "support")}
    assert all(set(c.domains) <= allowed for c in result.candidates)


async def test_co_usage_respects_candidate_limit() -> None:
    adapter = fixture_adapter()
    request = CoUsageRequest(time_range=TIME_RANGE, budget=make_budget(limit=1))
    with pytest.raises(RateLimitedError) as err:
        await adapter.co_usage_candidates(request, scope=make_scope())
    assert err.value.reason == "row_limit_exceeded"


def test_fixture_refused_outside_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "prod")
    monkeypatch.setenv("NS_CLOUD", "commercial")
    with pytest.raises(ForbiddenError) as err:
        FixtureAnalytics(build_dataset("commercial", 5), cloud="commercial")
    assert err.value.reason == "fixture_sandbox_only"
    FixtureAnalytics(build_dataset("commercial", 5), cloud="commercial", sandbox=True)


def test_fixture_allowed_under_local_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    FixtureAnalytics(build_dataset("commercial", 5), cloud="commercial")


def test_request_models_reject_free_text_and_extras() -> None:
    with pytest.raises(ValidationError):
        FilterClause(field=Dimension.MODEL, op=FilterOp.EQ, values=("x'; DROP TABLE t;--",))
    with pytest.raises(ValidationError):
        make_request(sql="SELECT 1")  # extra field
    with pytest.raises(ValidationError):
        AggregateRequest.model_validate(
            {"metric": "events", "aggregation": "count", "time_range": TIME_RANGE.model_dump()}
        )  # no budget
    with pytest.raises(ValidationError):
        AnalyticsBudget.model_validate(
            {"query": Budget(timeout_ms=10, limit=1, max_depth=0).model_dump()}
        )  # no scan or cost caps
    with pytest.raises(ValidationError):
        make_request(Metric.COST_AMOUNT, Aggregation.SUM)  # money without a currency
    with pytest.raises(ValidationError):
        make_request(Metric.EVENTS, Aggregation.SUM)
    with pytest.raises(ValidationError):
        make_request(Metric.DURATION_MS, Aggregation.APPROX_QUANTILE)  # missing quantile
