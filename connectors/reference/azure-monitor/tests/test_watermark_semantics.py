"""Watermark semantics: truncated slices, mid-poll 429s, empty source lists (PRP-09 r2 #7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from neurosphere_connector.health import HealthState
from neurosphere_connector_azure_monitor import (
    AzureMonitorConnector,
    MonitorSource,
    PollBounds,
    SourceKind,
)
from neurosphere_connector_azure_monitor.queries import MAX_ROWS
from neurosphere_core.errors import RateLimitedError

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
WS = "11111111-1111-1111-1111-111111111111"
URL = f"https://api.loganalytics.azure.com/v1/workspaces/{WS}/query"
SOURCES = [MonitorSource(SourceKind.LOG_ANALYTICS, WS)]
START = NOW - timedelta(hours=1)


async def _token(scope: str) -> str:
    return "fake-token-for-tests"


def _body(n_rows: int = 1, *, partial_error: bool = False) -> dict[str, Any]:
    body: dict[str, Any] = {
        "tables": [
            {
                "name": "PrimaryResult",
                "columns": [{"name": "TimeGenerated", "type": "datetime"}],
                "rows": [["2026-10-17T11:50:00Z"] for _ in range(n_rows)],
            }
        ]
    }
    if partial_error:
        body["error"] = {"code": "PartialError", "message": "x"}
    return body


def _connector(bounds: PollBounds) -> AzureMonitorConnector:
    async def sleeper(seconds: float) -> None:
        return None

    return AzureMonitorConnector(
        token_provider=_token, bounds=bounds, clock=lambda: NOW, sleeper=sleeper
    )


@respx.mock
@pytest.mark.parametrize(
    "truncated", [_body(MAX_ROWS), _body(2, partial_error=True)], ids=["max_rows", "partial_error"]
)
async def test_truncated_slice_is_reread_and_watermark_never_passes_it(
    truncated: dict[str, Any],
) -> None:
    route = respx.post(URL).mock(
        side_effect=[httpx.Response(200, json=truncated), httpx.Response(200, json=_body(1))]
    )
    result = await _connector(PollBounds(max_pages=2)).poll(SOURCES, watermark=START)
    assert route.call_count == 2
    assert result.shrunk_slices == 1
    assert result.truncated_pages == 1
    assert len(result.records) == 1  # truncated rows were discarded, only the re-read counts
    # Cursor moved over the re-read half slice only, never over the truncated 15 minutes.
    assert result.next_watermark == START + timedelta(minutes=7, seconds=30)
    assert result.partial is True
    assert result.stalled_slice_start is None


@respx.mock
async def test_next_poll_rereads_the_held_slice() -> None:
    respx.post(URL).mock(return_value=httpx.Response(200, json=_body(2, partial_error=True)))
    first = await _connector(PollBounds(max_pages=1)).poll(SOURCES, watermark=START)
    assert first.next_watermark == START
    assert first.records == []
    respx.reset()
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=_body(1)))
    second = await _connector(PollBounds(max_pages=1)).poll(SOURCES, watermark=first.next_watermark)
    assert route.calls.last.request.content.decode().count(START.strftime("%Y-%m-%dT%H:%M:%SZ")), (
        "the held slice starts at the same instant"
    )
    assert second.next_watermark == START + timedelta(minutes=15)
    assert len(second.records) == 1


@respx.mock
async def test_persistently_truncated_slice_is_bounded_and_reported() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=_body(MAX_ROWS)))
    bounds = PollBounds(max_pages=100, max_window=timedelta(hours=1))
    result = await _connector(bounds).poll(SOURCES, watermark=START)
    assert route.call_count < 10  # halves 15m down to the floor, then stops
    assert route.call_count < bounds.max_pages
    assert result.records == []
    assert result.next_watermark == START
    assert result.stalled_slice_start == START
    assert result.partial is True
    assert result.coverage.partial is True


@respx.mock
async def test_persistent_truncation_never_exceeds_page_budget() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=_body(MAX_ROWS)))
    result = await _connector(PollBounds(max_pages=3)).poll(SOURCES, watermark=START)
    assert route.call_count == 3
    assert result.next_watermark == START
    assert result.partial is True


@respx.mock
async def test_429_on_slice_two_returns_slice_one_records_partial_and_rate_limited() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json=_body(3))
        return httpx.Response(429, headers={"Retry-After": "9"})

    respx.post(URL).mock(side_effect=handler)
    c = _connector(PollBounds())
    result = await c.poll(SOURCES, watermark=START)
    assert len(result.records) == 3
    assert result.partial is True
    assert result.rate_limited is True
    assert result.retry_after_seconds == 9
    assert result.next_watermark == START + timedelta(minutes=15)  # slice two is re-polled
    health = await c.health()
    assert health.state is HealthState.RATE_LIMITED
    assert health.rate_limit.retry_after_seconds == 9


@respx.mock
async def test_429_on_first_slice_still_raises() -> None:
    respx.post(URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "9"}))
    with pytest.raises(RateLimitedError):
        await _connector(PollBounds()).poll(SOURCES, watermark=START)


async def test_empty_sources_do_not_advance_the_watermark() -> None:
    result = await _connector(PollBounds()).poll([], watermark=START)
    assert result.next_watermark == START
    assert result.records == []
    assert result.requests_made == 0
    assert result.partial is True
    assert result.coverage.fraction is None


async def test_empty_sources_without_watermark_return_start_not_horizon() -> None:
    result = await _connector(PollBounds()).poll([])
    assert result.next_watermark == NOW - timedelta(minutes=5) - timedelta(hours=1)
