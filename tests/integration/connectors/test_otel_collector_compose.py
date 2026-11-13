"""OTLP span -> composed OpenTelemetry Collector -> composed api ingest edge -> Event Hubs emulator.

PRP-09 item 10 (#49). Precondition (the test skips cleanly when it is not met)::

    NS_PRODUCER_CREDENTIAL=dev-ingest.<dev secret, docs/runbooks/ingest.md> \\
      docker compose --profile app --profile otel up -d --wait

CI does not run the ``integration`` marker for this test. G12 delta (recorded, not hidden): the
Event Hubs emulator has no Entra, so the producer identity is the edge's registered producer
credential (hash-compared bearer token, sent by the collector from its environment), not an
Entra principal; Entra producer identity stays with the live gate, reported OPEN.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
import uuid

import pytest
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.payload import HubMessage

from integration.ingestion.support import read_hub

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

COLLECTOR_HTTP = ("127.0.0.1", 4318)
API = ("127.0.0.1", 8000)
EVENTHUBS = ("127.0.0.1", 5672)
PRECONDITION = (
    "NS_PRODUCER_CREDENTIAL=<producer_id>.<secret> "
    "docker compose --profile app --profile otel up -d --wait"
)


def _port_open(address: tuple[str, int]) -> bool:
    try:
        with socket.create_connection(address, timeout=2):
            return True
    except OSError:
        return False


@pytest.fixture(scope="module", autouse=True)
def _require_stack() -> None:
    missing = [
        n
        for n, a in (("collector", COLLECTOR_HTTP), ("api", API), ("eventhubs", EVENTHUBS))
        if not _port_open(a)
    ]
    if missing:
        pytest.skip(f"compose stack not up ({', '.join(missing)}); run: {PRECONDITION}")


def _attr(key: str, value: str) -> dict[str, object]:
    return {"key": key, "value": {"stringValue": value}}


def _post_span(trace_id: str, span_id: str) -> int:
    document = {
        "resourceSpans": [
            {
                "resource": {"attributes": [_attr("service.name", "otel-compose-it")]},
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": span_id,
                                "name": "chat",
                                "kind": 3,
                                "startTimeUnixNano": "1790000000000000000",
                                # no end time and no token counts: unknown must stay null
                                "attributes": [
                                    _attr("gen_ai.request.model", "synthetic-model"),
                                    _attr("gen_ai.prompt", "COMPOSE-PROMPT-CANARY"),
                                    _attr("completion", "COMPOSE-COMPLETION-CANARY"),
                                    _attr("messages", "COMPOSE-MESSAGES-CANARY"),
                                    _attr("llm.response", "COMPOSE-RESPONSE-CANARY"),
                                ],
                            }
                        ]
                    }
                ],
            }
        ]
    }
    request = urllib.request.Request(
        "http://127.0.0.1:4318/v1/traces",
        data=json.dumps(document).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    deadline = time.monotonic() + 30
    while True:
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status
        except (urllib.error.URLError, ConnectionError):
            if time.monotonic() > deadline:
                raise
            time.sleep(1)


async def test_span_through_collector_lands_as_telemetry_event() -> None:
    trace_id = uuid.uuid4().hex
    span_id = uuid.uuid4().hex[:16]
    assert _post_span(trace_id, span_id) == 200

    needle = trace_id.encode()
    raw = await read_hub(lambda body: needle in body, max_seconds=90)
    assert raw, (
        "no event reached the hub: check the collector log and that NS_PRODUCER_CREDENTIAL was "
        "set when the stack came up"
    )
    messages = [HubMessage.from_bytes(r) for r in raw]
    events = [TelemetryEvent.model_validate(m.data) for m in messages]
    assert len(events) == 1
    event = events[0]
    assert event.trace_id is not None and event.trace_id.root == trace_id
    assert event.span_id is not None and event.span_id.root == span_id
    assert event.parent_span_id is None
    # Unknown stays null, never 0.
    assert event.token_breakdown is None
    assert event.duration_ms is None
    blob = b"".join(m.to_bytes() for m in messages)
    for canary in (b"PROMPT-CANARY", b"COMPLETION-CANARY", b"MESSAGES-CANARY", b"RESPONSE-CANARY"):
        assert canary not in blob
