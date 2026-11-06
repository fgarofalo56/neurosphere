"""APIM_USAGE_METRICS: fixed customMetrics KQL, App Insights routing, cost-center attribution."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from neurosphere_connector_azure_monitor import (
    AzureMonitorConnector,
    CostCenterIndex,
    MonitorSource,
    PollBounds,
    SourceKind,
    map_gateway_row,
)
from neurosphere_connector_azure_monitor.queries import APIM_USAGE_METRICS_COLUMNS, TEMPLATES

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 29, 10, 30, tzinfo=UTC)
APP = "33333333-3333-3333-3333-333333333333"
AI = "https://api.applicationinsights.io/v1/apps/{}/query"
FORBIDDEN = (
    "RequestMessages",
    "ResponseMessages",
    "RequestBody",
    "ResponseBody",
    "BackendRequestBody",
    "BackendResponseBody",
    "RequestHeaders",
    "ResponseHeaders",
    "BackendRequestHeaders",
    "BackendResponseHeaders",
    "TraceRecords",
)
MAP_ARGS: dict[str, Any] = {
    "cloud": "commercial",
    "customer_id": "cust-1",
    "source_id": "apim-poll",
}


async def _token(scope: str) -> str:
    return "fake-token-for-tests"


def _rows(name: str) -> list[dict[str, Any]]:
    table = json.loads((FIXTURES / name).read_text(encoding="utf-8"))["tables"][0]
    names = [c["name"] for c in table["columns"]]
    return [dict(zip(names, row, strict=True)) for row in table["rows"]]


def _gateway(**kw: Any) -> dict[str, Any]:
    row = _rows("apim_gateway_response.json")[0]
    return {**row, **kw}


def test_token_metrics_kql_is_a_fixed_allowlist() -> None:
    text = TEMPLATES[SourceKind.APIM_USAGE_METRICS]
    assert text.startswith("customMetrics | where name in (")
    assert f"| project {APIM_USAGE_METRICS_COLUMNS} |" in text
    for name in FORBIDDEN:
        assert name not in text, name
    assert "ago(" not in text
    assert "datetime(" not in text
    # customDimensions is only read per key, never projected whole.
    assert "project customDimensions" not in text
    assert ", customDimensions" not in APIM_USAGE_METRICS_COLUMNS


@respx.mock
async def test_poll_uses_app_insights_endpoint_with_timespan() -> None:
    fixture = json.loads((FIXTURES / "apim_usage_metrics_response.json").read_text("utf-8"))
    route = respx.get(AI.format(APP)).mock(return_value=httpx.Response(200, json=fixture))
    connector = AzureMonitorConnector(
        token_provider=_token, bounds=PollBounds(max_pages=1), clock=lambda: NOW
    )
    result = await connector.poll([MonitorSource(SourceKind.APIM_USAGE_METRICS, APP)])
    params = route.calls[0].request.url.params
    assert params["query"] == TEMPLATES[SourceKind.APIM_USAGE_METRICS]
    assert "/" in params["timespan"]
    assert [r["source_kind"] for r in result.records] == ["apim_usage_metrics"] * 4
    assert result.freshness.lag_ms is not None


def test_cost_center_attributes_by_api_and_subscription() -> None:
    index = CostCenterIndex(_rows("apim_usage_metrics_response.json"))
    assert map_gateway_row(_gateway(), cost_centers=index, **MAP_ARGS).cost.tags == {
        "cost_center": "CC-4410"
    }


def test_na_or_unmatched_subscription_gets_no_tag() -> None:
    index = CostCenterIndex(_rows("apim_usage_metrics_response.json"))
    na = _gateway(ApiId="echo-api", ApimSubscriptionId="sub-0002-raw-value")
    unknown = _gateway(ApimSubscriptionId="sub-9999")
    no_sub = _gateway(ApimSubscriptionId=None)
    for row in (na, unknown, no_sub):
        assert map_gateway_row(row, cost_centers=index, **MAP_ARGS).cost.tags is None


def test_falls_back_to_subscription_when_api_differs() -> None:
    index = CostCenterIndex(_rows("apim_usage_metrics_response.json"))
    row = _gateway(ApiId="other-api")
    assert map_gateway_row(row, cost_centers=index, **MAP_ARGS).cost.tags == {
        "cost_center": "CC-4410"
    }


def test_ambiguous_key_is_never_guessed() -> None:
    metric = {"SubscriptionId": "s", "ApiId": "a", "x-ns-cost-center": "CC-1"}
    other = {**metric, "x-ns-cost-center": "CC-2"}
    index = CostCenterIndex([metric, other])
    row = _gateway(ApiId="a", ApimSubscriptionId="s")
    assert map_gateway_row(row, cost_centers=index, **MAP_ARGS).cost.tags is None
    # A more specific (api, subscription) pair still resolves when the subscription is ambiguous.
    third = {"SubscriptionId": "s", "ApiId": "b", "x-ns-cost-center": "CC-3"}
    index = CostCenterIndex([metric, third])
    assert map_gateway_row(
        _gateway(ApiId="b", ApimSubscriptionId="s"), cost_centers=index, **MAP_ARGS
    ).cost.tags == {"cost_center": "CC-3"}


@pytest.mark.parametrize("value", ["N/A", "", None, "has space", "-lead", "x" * 129])
def test_invalid_metric_values_are_not_indexed(value: str | None) -> None:
    index = CostCenterIndex([{"SubscriptionId": "s", "x-ns-cost-center": value}])
    assert len(index) == 0
    assert index.lookup({"ApimSubscriptionId": "s"}) is None


def test_row_dimension_wins_over_index() -> None:
    index = CostCenterIndex([{"SubscriptionId": "s", "x-ns-cost-center": "CC-1"}])
    row = _gateway(ApimSubscriptionId="s", **{"x-ns-cost-center": "CC-ROW"})
    assert map_gateway_row(row, cost_centers=index, **MAP_ARGS).cost.tags == {
        "cost_center": "CC-ROW"
    }


def test_replaying_metric_rows_yields_one_stable_attribution() -> None:
    rows = _rows("apim_usage_metrics_response.json")
    once = CostCenterIndex(rows)
    twice = CostCenterIndex([*rows, *rows])
    gateway = _gateway()
    first = map_gateway_row(gateway, cost_centers=once, **MAP_ARGS)
    again = map_gateway_row(gateway, cost_centers=twice, **MAP_ARGS)
    assert first.cost.tags == again.cost.tags == {"cost_center": "CC-4410"}
    assert first.cost.dedupe_key == again.cost.dedupe_key
