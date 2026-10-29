"""APIM gateway and MCP source kinds: KQL allowlist, join mapping, hashing, Government rule."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from neurosphere_connector_azure_monitor import (
    AzureMonitorConnector,
    MonitorSource,
    PollBounds,
    SourceKind,
    endpoints_for,
    map_gateway_row,
    map_mcp_row,
)
from neurosphere_connector_azure_monitor.queries import TEMPLATES
from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.errors import CapabilityUnavailableError

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 29, 10, 30, tzinfo=UTC)
WS = "11111111-1111-1111-1111-111111111111"
LA = "https://api.loganalytics.azure.com/v1/workspaces/{}/query"
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
GATEWAY_COLUMNS = (
    "TimeGenerated, CorrelationId, ApiId, ApiRevision, OperationId, ProductId, ApimSubscriptionId,"
    " BackendId, BackendResponseCode, ResponseCode, IsRequestSuccess, TotalTime, BackendTime,"
    " Region, _ResourceId"
)
LLM_COLUMNS = (
    "ModelName, DeploymentName, PromptTokens, CompletionTokens, TotalTokens,"
    " IsStreamCompletion, ApiVersion"
)
MAP_ARGS: dict[str, Any] = {
    "cloud": "commercial",
    "customer_id": "cust-1",
    "source_id": "apim-poll",
    "domain_id": "dom-1",
}


async def _token(scope: str) -> str:
    return "fake-token-for-tests"


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _rows(name: str) -> list[dict[str, Any]]:
    table = _fixture(name)["tables"][0]
    names = [c["name"] for c in table["columns"]]
    return [dict(zip(names, row, strict=True)) for row in table["rows"]]


def _connector(**kw: Any) -> AzureMonitorConnector:
    return AzureMonitorConnector(
        token_provider=_token,
        bounds=PollBounds(max_pages=1),
        clock=lambda: NOW,
        **kw,
    )


def test_kql_constants_never_project_bodies_headers_or_traces() -> None:
    for kind in (SourceKind.APIM_GATEWAY, SourceKind.APIM_MCP):
        text = TEMPLATES[kind]
        for name in FORBIDDEN:
            assert name not in text, (kind, name)


def test_gateway_kql_projects_exactly_the_allowlist_and_joins_on_correlation_id() -> None:
    text = TEMPLATES[SourceKind.APIM_GATEWAY]
    assert text.startswith(f"ApiManagementGatewayLogs | project {GATEWAY_COLUMNS} |")
    assert f"ApiManagementGatewayLlmLog | project CorrelationId, {LLM_COLUMNS})" in text
    assert "join kind=leftouter" in text
    assert "on CorrelationId" in text
    assert "order by TimeGenerated asc" in text


def test_mcp_kql_projects_exactly_the_allowlist() -> None:
    text = TEMPLATES[SourceKind.APIM_MCP]
    assert text.startswith(
        "ApiManagementGatewayMCPLog | project"
        " TimeGenerated, CorrelationId, ToolName, ToolCount, TransportType, _ResourceId |"
    )


def test_kql_has_no_interpolated_window() -> None:
    for kind in (SourceKind.APIM_GATEWAY, SourceKind.APIM_MCP):
        assert "ago(" not in TEMPLATES[kind]
        assert "datetime(" not in TEMPLATES[kind]


@respx.mock
async def test_gateway_poll_sends_fixed_kql_with_timespan_and_maps_rows() -> None:
    route = respx.post(LA.format(WS)).mock(
        return_value=httpx.Response(200, json=_fixture("apim_gateway_response.json"))
    )
    result = await _connector().poll([MonitorSource(SourceKind.APIM_GATEWAY, WS)])
    body = json.loads(route.calls[0].request.content)
    assert body["query"] == TEMPLATES[SourceKind.APIM_GATEWAY]
    assert "/" in body["timespan"]
    assert result.coverage.answered_sources == 1
    assert result.freshness.lag_ms is not None
    assert [r["source_kind"] for r in result.records] == ["apim_gateway"] * 2
    # No column was stripped as a body field, and the poller's extra keys are tolerated.
    mapped = [map_gateway_row(r, **MAP_ARGS) for r in result.records]
    assert [m.cost.dedupe_key for m in mapped] == ["corr-llm-0001", "corr-plain-0002"]


def test_join_maps_to_one_event_and_one_cost_per_correlation_id() -> None:
    rows = _rows("apim_gateway_response.json")
    mapped = [map_gateway_row(r, **MAP_ARGS) for r in rows]
    assert len(mapped) == len({r["CorrelationId"] for r in rows}) == 2
    llm = mapped[0]
    assert llm.telemetry.request_id is not None
    assert llm.telemetry.request_id.root == "corr-llm-0001"
    assert llm.telemetry.event_id.root == "corr-llm-0001"
    assert llm.cost.dedupe_key == "corr-llm-0001"
    assert llm.cost.observation_source == "gateway"
    assert llm.cost.amount is None
    assert llm.cost.currency is None
    assert llm.cost.model == "gpt-4o"
    assert llm.cost.deployment_name == "gpt-4o-prod"
    assert llm.cost.token_breakdown is not None
    assert llm.cost.token_breakdown.input == 120
    assert llm.cost.token_breakdown.output == 45
    assert llm.cost.total_tokens == 165
    assert llm.cost.api_id == "openai-api"
    assert llm.cost.product_id == "ai-product"
    assert llm.cost.backend_id == "foundry-backend"
    assert llm.cost.response_code == 200
    assert llm.cost.region == "East US"
    assert llm.telemetry.outcome == "success"
    assert llm.telemetry.duration_ms == 812
    assert llm.cost.backend_time_ms == 790
    assert llm.telemetry.event_time.root == "2026-10-29T10:00:01.123456Z"
    assert llm.telemetry.span_kind == "model_call"


def test_subscription_id_is_hashed_never_raw() -> None:
    row = _rows("apim_gateway_response.json")[0]
    mapped = map_gateway_row(row, **MAP_ARGS)
    expected = hashlib.sha256(b"sub-0001-raw-value").hexdigest()
    assert mapped.cost.subscription_id_hash == expected
    assert "sub-0001-raw-value" not in mapped.model_dump_json()


def test_row_without_llm_side_maps_with_null_tokens() -> None:
    row = _rows("apim_gateway_response.json")[1]
    mapped = map_gateway_row(row, **MAP_ARGS)
    assert mapped.telemetry.token_breakdown is None
    assert mapped.cost.token_breakdown is None
    assert mapped.cost.total_tokens is None
    assert mapped.cost.model is None
    assert mapped.cost.deployment_name is None
    assert mapped.cost.backend_id is None
    assert mapped.telemetry.span_kind == "request"
    assert mapped.cost.amount is None


def test_missing_subscription_id_stays_null() -> None:
    row = {**_rows("apim_gateway_response.json")[1], "ApimSubscriptionId": None}
    assert map_gateway_row(row, **MAP_ARGS).cost.subscription_id_hash is None


def test_failed_request_maps_to_error_outcome_and_unknown_when_absent() -> None:
    base = _rows("apim_gateway_response.json")[1]
    assert map_gateway_row({**base, "IsRequestSuccess": False}, **MAP_ARGS).telemetry.outcome == (
        "error"
    )
    assert map_gateway_row({**base, "IsRequestSuccess": None}, **MAP_ARGS).telemetry.outcome == (
        "unknown"
    )


def test_row_without_correlation_id_is_refused() -> None:
    row = {**_rows("apim_gateway_response.json")[0], "CorrelationId": None}
    with pytest.raises(ValueError, match="CorrelationId"):
        map_gateway_row(row, **MAP_ARGS)


def test_mcp_row_maps_to_tool_call_event_with_tool_and_transport() -> None:
    row = _rows("apim_mcp_response.json")[0]
    mapped = map_mcp_row(row, **MAP_ARGS)
    assert mapped.tool_name == "search_docs"
    assert mapped.tool_count == 1
    assert mapped.transport_type == "streamable-http"
    assert mapped.telemetry.span_kind == "tool_call"
    assert mapped.telemetry.request_id is not None
    assert mapped.telemetry.request_id.root == "corr-mcp-0003"
    assert mapped.telemetry.event_id.root == "corr-mcp-0003:mcp"


@respx.mock
async def test_mcp_poll_sends_mcp_kql() -> None:
    route = respx.post(LA.format(WS)).mock(
        return_value=httpx.Response(200, json=_fixture("apim_mcp_response.json"))
    )
    result = await _connector().poll([MonitorSource(SourceKind.APIM_MCP, WS)])
    assert json.loads(route.calls[0].request.content)["query"] == TEMPLATES[SourceKind.APIM_MCP]
    assert [r["ToolName"] for r in result.records] == ["search_docs"]


def test_government_still_requires_opt_in_for_new_kinds() -> None:
    with pytest.raises(CapabilityUnavailableError):
        AzureMonitorConnector(token_provider=_token, cloud=CloudName.GOVERNMENT)


@respx.mock
@pytest.mark.parametrize("kind", [SourceKind.APIM_GATEWAY, SourceKind.APIM_MCP])
async def test_government_with_opt_in_uses_gov_host_never_commercial(kind: SourceKind) -> None:
    fixture = (
        "apim_gateway_response.json"
        if kind is SourceKind.APIM_GATEWAY
        else ("apim_mcp_response.json")
    )
    gov_host = endpoints_for(CloudName.GOVERNMENT, allow_unverified_government=True)
    gov = respx.post(f"{gov_host.log_analytics_base}/v1/workspaces/{WS}/query").mock(
        return_value=httpx.Response(200, json=_fixture(fixture))
    )
    commercial = respx.post(LA.format(WS)).mock(return_value=httpx.Response(200, json={}))
    c = _connector(cloud=CloudName.GOVERNMENT, allow_unverified_government=True)
    await c.poll([MonitorSource(kind, WS)])
    assert gov.called
    assert not commercial.called
