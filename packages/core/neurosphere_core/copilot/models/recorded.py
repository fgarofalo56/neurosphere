"""Recorded-fixture adapter and replay helpers (no network, ever).

Scenarios live under ``fixtures/<scenario>/``:

* ``conversation.json`` - the :class:`ModelRequest` and the normalized events every adapter
  must produce for it;
* ``approved_endpoint.json`` / ``foundry_agent.json`` - the recorded provider exchange (the
  redacted request body the adapter sends, and the streamed provider response).

:class:`FixtureAdapter` replays ``conversation.json`` and is the default adapter for the
sandbox and CI. :func:`replay_transport` serves a provider recording to the REST adapters
through an httpx ``MockTransport``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Final

import httpx
from pydantic import BaseModel, ConfigDict, TypeAdapter

from neurosphere_core.copilot.models.protocol import AdapterDescriptor
from neurosphere_core.copilot.models.types import ModelEvent, ModelRequest

FIXTURES_DIR: Final = Path(__file__).parent / "fixtures"

_EVENTS: Final[TypeAdapter[list[ModelEvent]]] = TypeAdapter(list[ModelEvent])


class RecordedConversation(BaseModel):
    """A request plus the normalized events the action contract expects for it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request: ModelRequest
    events: tuple[ModelEvent, ...]


class HttpRecording(BaseModel):
    """One recorded provider exchange: the outbound JSON body and the streamed response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_body: dict[str, Any]
    # Each item is serialized as one SSE ``data:`` line (strings are written verbatim).
    stream: tuple[Any, ...]
    status: int = 200


def scenarios() -> list[str]:
    """Names of the recorded scenarios, sorted."""
    return sorted(p.name for p in FIXTURES_DIR.iterdir() if (p / "conversation.json").is_file())


def _read(scenario: str, name: str) -> Any:
    path = FIXTURES_DIR / scenario / name
    if path.parent.parent != FIXTURES_DIR or not path.is_file():
        raise FileNotFoundError(f"no recorded fixture {scenario}/{name}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_conversation(scenario: str) -> RecordedConversation:
    doc = _read(scenario, "conversation.json")
    return RecordedConversation(
        request=ModelRequest.model_validate(doc["request"]),
        events=tuple(_EVENTS.validate_python(doc["events"])),
    )


def load_http_recording(scenario: str, provider: str) -> HttpRecording:
    """``provider`` is ``approved_endpoint`` or ``foundry_agent``."""
    return HttpRecording.model_validate(_read(scenario, f"{provider}.json"))


def replay_transport(
    recording: HttpRecording, captured: list[httpx.Request] | None = None
) -> httpx.MockTransport:
    """A transport that records outbound requests into ``captured`` and replays the stream."""
    lines = [
        f"data: {item if isinstance(item, str) else json.dumps(item)}\n\n"
        for item in recording.stream
    ]
    content = "".join(lines).encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        return httpx.Response(
            recording.status, headers={"content-type": "text/event-stream"}, content=content
        )

    return httpx.MockTransport(handler)


class FixtureAdapter:
    """Replays a recorded conversation's normalized events; never contacts a model."""

    def __init__(self, scenario: str | RecordedConversation) -> None:
        self._recorded = load_conversation(scenario) if isinstance(scenario, str) else scenario
        self._descriptor = AdapterDescriptor(kind="fixture", name="recorded", synthetic=True)

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._descriptor

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        del request  # replay ignores the live request by design
        for event in self._recorded.events:
            yield event
