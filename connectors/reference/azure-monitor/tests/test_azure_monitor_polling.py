"""Azure Monitor connector: bounded polling, freshness/coverage, throttling, cloud selection."""

from __future__ import annotations

import inspect
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from neurosphere_connector.health import HealthState
from neurosphere_connector.testing import ConnectorContractSuite
from neurosphere_connector_azure_monitor import (
    ENDPOINTS,
    AzureMonitorConnector,
    MonitorSource,
    PollBounds,
    SourceKind,
    endpoints_for,
)
from neurosphere_connector_azure_monitor.queries import TEMPLATES
from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.errors import CapabilityUnavailableError, RateLimitedError

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
WS_A = "11111111-1111-1111-1111-111111111111"
WS_B = "22222222-2222-2222-2222-222222222222"
APP = "33333333-3333-3333-3333-333333333333"
LA = "https://api.loganalytics.azure.com/v1/workspaces/{}/query"
AI = "https://api.applicationinsights.io/v1/apps/{}/query"


async def _token(scope: str) -> str:
    return "fake-token-for-tests"


def _body(rows: list[list[Any]] | None = None, *, partial: bool = False) -> dict[str, Any]:
    body: dict[str, Any] = {
        "tables": [
            {
                "name": "PrimaryResult",
                "columns": [
                    {"name": "TimeGenerated", "type": "datetime"},
                    {"name": "requests", "type": "long"},
                    {"name": "prompt", "type": "string"},
                ],
                "rows": rows if rows is not None else [["2026-10-17T11:50:00Z", 5, "secret text"]],
            }
        ]
    }
    if partial:
        body["error"] = {"code": "PartialError", "message": "x"}
    return body


def _connector(
    sleeps: list[float] | None = None, *, bounds: PollBounds | None = None, **kw: Any
) -> AzureMonitorConnector:
    async def sleeper(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    return AzureMonitorConnector(
        token_provider=_token,
        bounds=bounds or PollBounds(),
        clock=lambda: NOW,
        sleeper=sleeper,
        **kw,
    )


LA_SOURCES = [MonitorSource(SourceKind.LOG_ANALYTICS, WS_A)]


@respx.mock
async def test_result_carries_freshness_and_coverage() -> None:
    respx.post(LA.format(WS_A)).mock(return_value=httpx.Response(200, json=_body()))
    respx.post(LA.format(WS_B)).mock(return_value=httpx.Response(200, json=_body()))
    c = _connector()
    result = await c.poll(
        [
            MonitorSource(SourceKind.LOG_ANALYTICS, WS_A),
            MonitorSource(SourceKind.LOG_ANALYTICS, WS_B),
        ]
    )
    assert result.coverage.fraction == 1.0
    assert result.freshness.lag_ms == 10 * 60 * 1000
    assert not result.partial
    assert (await c.coverage()).fraction == 1.0
    assert (await c.freshness()).lag_ms == 10 * 60 * 1000
    assert (await c.health()).state is HealthState.HEALTHY


@respx.mock
async def test_unknown_lag_is_none_not_zero() -> None:
    respx.post(LA.format(WS_A)).mock(return_value=httpx.Response(200, json=_body(rows=[])))
    result = await _connector().poll(LA_SOURCES)
    assert result.records == []
    assert result.freshness.lag_ms is None


@respx.mock
async def test_prompt_like_fields_are_dropped_before_output() -> None:
    respx.post(LA.format(WS_A)).mock(return_value=httpx.Response(200, json=_body()))
    result = await _connector().poll(LA_SOURCES)
    assert result.records
    assert all("prompt" not in r for r in result.records)
    assert result.dropped_body_fields.get("prompt", 0) >= 1
    assert "secret text" not in json.dumps(result.records, default=str)


@respx.mock
async def test_page_budget_exceeded_returns_partial_with_bounded_calls() -> None:
    route = respx.post(LA.format(WS_A)).mock(return_value=httpx.Response(200, json=_body()))
    c = _connector(bounds=PollBounds(max_pages=2))
    result = await c.poll(LA_SOURCES)
    assert route.call_count == 2  # never a third page
    assert result.partial is True
    assert result.pages_used == 2
    assert result.requests_made == 2
    assert result.coverage.partial is True
    assert result.next_watermark == NOW - timedelta(minutes=5) - timedelta(hours=1) + timedelta(
        minutes=30
    )


@respx.mock
async def test_window_within_budget_is_complete_and_advances_to_horizon() -> None:
    route = respx.post(LA.format(WS_A)).mock(return_value=httpx.Response(200, json=_body()))
    result = await _connector().poll(LA_SOURCES)
    assert route.call_count == 4
    assert result.partial is False
    assert result.next_watermark == NOW - timedelta(minutes=5)


@respx.mock
async def test_max_window_caps_a_stale_watermark() -> None:
    route = respx.post(LA.format(WS_A)).mock(return_value=httpx.Response(200, json=_body()))
    bounds = PollBounds(
        max_pages=100, max_window=timedelta(hours=1), slice_length=timedelta(minutes=30)
    )
    result = await _connector(bounds=bounds).poll(LA_SOURCES, watermark=NOW - timedelta(days=3))
    assert route.call_count == 2
    assert result.partial is True
    assert result.next_watermark == NOW - timedelta(days=3) + timedelta(hours=1)


@respx.mock
async def test_missing_source_lowers_coverage_and_holds_watermark() -> None:
    respx.post(LA.format(WS_A)).mock(return_value=httpx.Response(200, json=_body()))
    respx.post(LA.format(WS_B)).mock(return_value=httpx.Response(403, json={"error": {}}))
    start = NOW - timedelta(hours=1)
    result = await _connector().poll(
        [
            MonitorSource(SourceKind.LOG_ANALYTICS, WS_A),
            MonitorSource(SourceKind.LOG_ANALYTICS, WS_B),
        ],
        watermark=start,
    )
    assert result.coverage.fraction == 0.5
    assert result.partial is True
    assert result.failed_sources == {WS_B: "forbidden"}
    assert result.next_watermark == start  # no silent gap


@respx.mock
async def test_all_sources_failing_raises_and_health_fails() -> None:
    respx.post(LA.format(WS_A)).mock(return_value=httpx.Response(401))
    c = _connector()
    with pytest.raises(Exception, match="rejected the token"):
        await c.poll(LA_SOURCES)
    assert (await c.health()).state is HealthState.FAILING


@respx.mock
async def test_429_honors_retry_after_then_succeeds() -> None:
    sleeps: list[float] = []
    route = respx.post(LA.format(WS_A)).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json=_body()),
        ]
    )
    c = _connector(sleeps, bounds=PollBounds(max_pages=1))
    result = await c.poll(LA_SOURCES)
    assert sleeps == [7]
    assert route.call_count == 2
    assert result.pages_used == 1


@respx.mock
async def test_429_exhausted_maps_to_rate_limited_health() -> None:
    sleeps: list[float] = []
    route = respx.post(LA.format(WS_A)).mock(
        return_value=httpx.Response(429, headers={"Retry-After": "9"})
    )
    c = _connector(sleeps)
    with pytest.raises(RateLimitedError) as info:
        await c.poll(LA_SOURCES)
    assert info.value.retry_after_seconds == 9
    assert route.call_count == 3  # bounded by max_attempts
    assert sleeps == [9, 9]
    health = await c.health()
    assert health.state is HealthState.RATE_LIMITED
    assert health.rate_limit.limited is True
    assert health.rate_limit.retry_after_seconds == 9


@respx.mock
async def test_429_without_header_uses_bounded_exponential_backoff() -> None:
    sleeps: list[float] = []
    respx.post(LA.format(WS_A)).mock(return_value=httpx.Response(429))
    with pytest.raises(RateLimitedError):
        await _connector(sleeps, bounds=PollBounds(max_attempts=4, max_backoff_s=3)).poll(
            LA_SOURCES
        )
    assert sleeps == [1, 2, 3]


@respx.mock
async def test_retry_after_above_cap_is_not_slept() -> None:
    sleeps: list[float] = []
    route = respx.post(LA.format(WS_A)).mock(
        return_value=httpx.Response(429, headers={"Retry-After": "3600"})
    )
    with pytest.raises(RateLimitedError) as info:
        await _connector(sleeps).poll(LA_SOURCES)
    assert sleeps == []
    assert route.call_count == 1
    assert info.value.retry_after_seconds == 3600


@respx.mock
async def test_commercial_hosts_and_request_shape() -> None:
    la = respx.post(LA.format(WS_A)).mock(return_value=httpx.Response(200, json=_body()))
    ai = respx.get(AI.format(APP)).mock(return_value=httpx.Response(200, json=_body()))
    c = _connector(bounds=PollBounds(max_pages=1))
    await c.poll(
        [MonitorSource(SourceKind.LOG_ANALYTICS, WS_A), MonitorSource(SourceKind.APP_INSIGHTS, APP)]
    )
    sent = json.loads(la.calls.last.request.content)
    assert sent["query"] == TEMPLATES[SourceKind.LOG_ANALYTICS]
    assert "/" in sent["timespan"]
    assert la.calls.last.request.headers["Authorization"] == "Bearer fake-token-for-tests"
    assert ai.calls.last.request.url.params["query"] == TEMPLATES[SourceKind.APP_INSIGHTS]


@respx.mock
async def test_government_uses_gov_host_never_commercial() -> None:
    gov = respx.post("https://api.loganalytics.us/v1/workspaces/" + WS_A + "/query").mock(
        return_value=httpx.Response(200, json=_body())
    )
    commercial = respx.post(LA.format(WS_A)).mock(return_value=httpx.Response(200, json=_body()))
    c = _connector(
        cloud=CloudName.GOVERNMENT,
        allow_unverified_government=True,
        bounds=PollBounds(max_pages=1),
    )
    await c.poll(LA_SOURCES)
    assert gov.called
    assert not commercial.called


def test_government_requires_opt_in_and_app_insights_is_disabled() -> None:
    with pytest.raises(CapabilityUnavailableError):
        endpoints_for(CloudName.GOVERNMENT)
    gov = endpoints_for(CloudName.GOVERNMENT, allow_unverified_government=True)
    assert gov.log_analytics_base == "https://api.loganalytics.us"
    assert gov.app_insights_base is None
    assert gov.verified is False
    assert set(ENDPOINTS) == set(CloudName)
    commercial = endpoints_for(CloudName.COMMERCIAL)
    assert commercial.log_analytics_base == "https://api.loganalytics.azure.com"


@respx.mock
async def test_government_app_insights_source_is_failed_not_rerouted() -> None:
    commercial = respx.get(AI.format(APP)).mock(return_value=httpx.Response(200, json=_body()))
    c = _connector(cloud=CloudName.GOVERNMENT, allow_unverified_government=True)
    with pytest.raises(Exception, match="unavailable"):
        await c.poll([MonitorSource(SourceKind.APP_INSIGHTS, APP)])
    assert not commercial.called


def test_no_free_form_query_input() -> None:
    assert list(inspect.signature(AzureMonitorConnector.poll).parameters) == [
        "self",
        "sources",
        "watermark",
    ]
    with pytest.raises(ValueError, match="GUID"):
        MonitorSource(SourceKind.LOG_ANALYTICS, "x/../../query?query=evil")
    assert all("{" not in t for t in TEMPLATES.values())  # no interpolation points


def test_manifest_is_advisory_vault_only_and_cites_the_api() -> None:
    m = _connector().manifest
    assert m.advisory is True
    assert m.write_support.supported is False
    assert m.credential_refs == []
    assert m.supported_clouds == ["commercial"]
    assert m.documentation_url is not None
    assert "learn.microsoft.com/en-us/azure/azure-monitor/logs/api" in m.documentation_url


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("NS_LIVE_APPROVED") != "1", reason="needs NS_LIVE_APPROVED=1")
def test_live_placeholder() -> None:
    pytest.skip("no live workspace configured; G04 stays OPEN")


class TestAzureMonitorContract(ConnectorContractSuite):
    @pytest.fixture
    def connector(self) -> AzureMonitorConnector:
        return _connector()
