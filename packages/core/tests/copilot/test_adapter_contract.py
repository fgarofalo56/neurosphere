"""One action-contract suite, run against every adapter (PRP-19 item 3).

Swapping the adapter must leave this green: the fixture adapter, the approved-endpoint adapter
(recorded chat-completions HTTP) and the Foundry Agent adapter (recorded Responses HTTP) all
normalize the same recorded conversation to the same events. No test opens a socket; the REST
adapters run on an httpx ``MockTransport``.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from azure.core.credentials import AccessToken
from neurosphere_core.copilot.models import (
    ActionSuggestion,
    AdapterConfig,
    ApprovedEndpointAdapter,
    Completed,
    FixtureAdapter,
    FoundryAgentAdapter,
    ModelAdapter,
    ModelEvent,
    TextDelta,
    ToolCallRequested,
    collapse_text,
)
from neurosphere_core.copilot.models.recorded import (
    HttpRecording,
    load_conversation,
    load_http_recording,
    replay_transport,
    scenarios,
)
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    NeuroSphereError,
    RateLimitedError,
    UnauthorizedError,
)

KINDS = ("fixture", "approved_endpoint", "foundry_agent")
SCENARIOS = scenarios()


class _Credential:
    """Managed-identity stand-in: a per-run random token, no network."""

    def __init__(self) -> None:
        self.token = f"tok-{uuid.uuid4().hex}"
        self.scopes: list[str] = []

    async def get_token(self, *scopes: str, **_kwargs: Any) -> AccessToken:
        self.scopes.extend(scopes)
        return AccessToken(self.token, int(time.time()) + 3600)

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> _Credential:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


def _make(
    kind: str,
    scenario: str,
    credential: _Credential,
    captured: list[httpx.Request],
    recording: HttpRecording | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ModelAdapter:
    if kind == "fixture":
        return FixtureAdapter(scenario)
    rec = recording or load_http_recording(scenario, kind)
    transport = transport or replay_transport(rec, captured)
    if kind == "approved_endpoint":
        return ApprovedEndpointAdapter(
            AdapterConfig(
                kind="approved_endpoint",
                endpoint="https://ns-test.openai.azure.us",
                deployment="gpt-4o",
            ),
            cloud="government",
            credential=credential,  # pyright: ignore[reportArgumentType]
            transport=transport,
        )
    return FoundryAgentAdapter(
        AdapterConfig(
            kind="foundry_agent",
            endpoint="https://ns-test.services.ai.azure.us/api/projects/ns",
            deployment="ns-copilot",
            oauth_scope="https://ai.azure.us/.default",
        ),
        cloud="government",
        credential=credential,  # pyright: ignore[reportArgumentType]
        transport=transport,
    )


async def _collect(adapter: ModelAdapter, scenario: str) -> list[ModelEvent]:
    request = load_conversation(scenario).request
    return [event async for event in adapter.stream(request)]


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("kind", KINDS)
async def test_adapter_emits_the_recorded_normalized_events(kind: str, scenario: str) -> None:
    events = await _collect(_make(kind, scenario, _Credential(), []), scenario)
    expected = list(load_conversation(scenario).events)
    assert collapse_text(events) == collapse_text(expected)


@pytest.mark.parametrize("scenario", SCENARIOS)
async def test_swapping_adapters_yields_identical_streams(scenario: str) -> None:
    streams = [
        collapse_text(await _collect(_make(kind, scenario, _Credential(), []), scenario))
        for kind in KINDS
    ]
    assert streams[0] == streams[1] == streams[2]


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("kind", KINDS)
async def test_stream_shape_is_text_then_calls_then_one_completed(kind: str, scenario: str) -> None:
    events = await _collect(_make(kind, scenario, _Credential(), []), scenario)
    assert isinstance(events[-1], Completed)
    assert sum(isinstance(e, Completed) for e in events) == 1
    kinds = [type(e) for e in events[:-1]]
    # Once a non-text event appears, no further text follows.
    first_non_text = next((i for i, k in enumerate(kinds) if k is not TextDelta), len(kinds))
    assert all(k is not TextDelta for k in kinds[first_non_text:])
    assert isinstance(events[0], TextDelta), "first token must stream before any tool call"
    saw_calls = any(isinstance(e, ToolCallRequested | ActionSuggestion) for e in events)
    assert events[-1].stop_reason == ("tool_calls" if saw_calls else "end_turn")
    assert events[-1].usage.input_tokens is not None


async def test_suggest_action_becomes_an_action_suggestion_on_every_adapter() -> None:
    for kind in KINDS:
        events = await _collect(
            _make(kind, "action_suggestion", _Credential(), []), "action_suggestion"
        )
        suggestions = [e for e in events if isinstance(e, ActionSuggestion)]
        assert len(suggestions) == 1, kind
        assert suggestions[0].action_type == "model_swap"
        assert suggestions[0].target_ref == "asset-summarizer"
        assert not any(isinstance(e, ToolCallRequested) for e in events), kind


async def test_plain_tool_call_keeps_raw_arguments_on_every_adapter() -> None:
    for kind in KINDS:
        events = await _collect(_make(kind, "tool_call", _Credential(), []), "tool_call")
        calls = [e for e in events if isinstance(e, ToolCallRequested)]
        assert [(c.tool_name, c.arguments) for c in calls] == [
            ("catalog_search", {"query": "summarizer", "limit": 5})
        ], kind


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("kind", ["approved_endpoint", "foundry_agent"])
async def test_outbound_request_matches_the_recording(kind: str, scenario: str) -> None:
    credential = _Credential()
    captured: list[httpx.Request] = []
    await _collect(_make(kind, scenario, credential, captured), scenario)
    assert len(captured) == 1
    sent = captured[0]
    assert json.loads(sent.content) == load_http_recording(scenario, kind).request_body
    assert sent.headers["authorization"] == f"Bearer {credential.token}"
    assert sent.method == "POST"
    host = urlsplit(str(sent.url)).hostname or ""
    assert host.endswith(".azure.us")
    expected_scope = {
        "approved_endpoint": "https://cognitiveservices.azure.us/.default",
        "foundry_agent": "https://ai.azure.us/.default",
    }[kind]
    assert credential.scopes == [expected_scope]


async def test_foundry_uses_api_version_v1_and_responses_path() -> None:
    captured: list[httpx.Request] = []
    await _collect(_make("foundry_agent", "text_answer", _Credential(), captured), "text_answer")
    url = urlsplit(str(captured[0].url))
    assert url.path.endswith("/openai/responses")
    assert "api-version=v1" in url.query


async def test_recorded_requests_never_carry_scope_fields() -> None:
    for scenario in SCENARIOS:
        for tool in load_conversation(scenario).request.tools:
            assert "domain_id" not in json.dumps(tool.parameters)
            assert "customer_id" not in json.dumps(tool.parameters)


def _status_adapter(kind: str, status: int, headers: dict[str, str] | None = None) -> ModelAdapter:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers=headers or {}, content=b'{"error":"secret-body"}')

    return _make(kind, "text_answer", _Credential(), [], transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("kind", ["approved_endpoint", "foundry_agent"])
@pytest.mark.parametrize(
    ("status", "headers", "expected"),
    [
        (401, None, UnauthorizedError),
        (403, None, ForbiddenError),
        (429, {"retry-after": "7"}, RateLimitedError),
        (503, None, DependencyTransientError),
        (400, None, DependencyTransientError),
    ],
)
async def test_http_failures_map_to_the_taxonomy_without_bodies(
    kind: str,
    status: int,
    headers: dict[str, str] | None,
    expected: type[NeuroSphereError],
) -> None:
    adapter = _status_adapter(kind, status, headers)
    with pytest.raises(expected) as info:
        await _collect(adapter, "text_answer")
    assert "secret-body" not in str(info.value)
    if status == 429:
        assert info.value.retry_after_seconds == 7
    if status == 400:
        assert info.value.status == 502


async def test_invalid_tool_arguments_are_a_502() -> None:
    recording = load_http_recording("tool_call", "approved_endpoint")
    broken = [
        json.loads(json.dumps(item)) if not isinstance(item, str) else item
        for item in recording.stream
    ]
    for item in broken:
        if isinstance(item, dict):
            for choice in item.get("choices", []):
                for part in choice["delta"].get("tool_calls", []):
                    if "arguments" in part["function"] and part.get("id") is None:
                        part["function"]["arguments"] = "}{"
    adapter = _make(
        "approved_endpoint",
        "tool_call",
        _Credential(),
        [],
        recording.model_copy(update={"stream": tuple(broken)}),
    )
    with pytest.raises(DependencyTransientError) as info:
        await _collect(adapter, "tool_call")
    assert info.value.status == 502


def test_recorded_scenarios_are_the_expected_set() -> None:
    assert SCENARIOS == ["action_suggestion", "text_answer", "tool_call"]
