"""PRP-103 item 3 review follow-ups: request correlation id end to end, no exception escapes a
capture job, and body/span index alignment around a rejected span."""

from __future__ import annotations

import json
import logging
import secrets
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from neurosphere_api.app import create_app
from neurosphere_api.ingest import (
    InMemoryPublisher,
    configure_ingest,
)
from neurosphere_api.ingest import capture as edge_module
from neurosphere_api.ingest import otlp_mapping as om
from neurosphere_api.ingest.capture import edge_correlation_id
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.audit.content_guard import assert_metadata_only
from neurosphere_core.cloud import Settings
from neurosphere_core.payload import find_body_fields

from . import edge_helpers as h
from .edge_helpers import BATCH, CUSTOMER, DOMAIN, TELEMETRY_TYPE, ce, rig, telemetry_data


@pytest.fixture(autouse=True)
def no_captured_value_in_logs(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    h.ISSUED.clear()
    caplog.set_level(logging.DEBUG)
    yield
    joined = "\n".join([caplog.text, *(repr(r.__dict__) + r.getMessage() for r in caplog.records)])
    for value in h.ISSUED:
        assert value not in joined


async def test_request_correlation_id_reaches_the_capture_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``x-correlation-id`` through the real app and ingest router to the audit draft."""
    secret = secrets.token_urlsafe(24)  # fake, generated per test
    registration = h.producer(secret_sha256=h.hash_secret(secret))
    publisher = InMemoryPublisher()
    service = h.service(publisher, registration)
    capture, store, audit = await h.edge_capture(tmp_path, monkeypatch)
    service.attach_capture(capture)
    app = create_app(Settings(env="local"))
    configure_ingest(app, service)
    correlation = "req-" + secrets.token_hex(8)
    body = [ce(TELEMETRY_TYPE, telemetry_data("evt-http", domain_id=DOMAIN, prompt=h.canary()))]

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://edge.test") as client:
        resp = await client.post(
            "/api/v1/ingest/events",
            content=json.dumps(body),
            headers={
                "content-type": BATCH,
                "authorization": f"Bearer {registration.producer_id}.{secret}",
                "x-correlation-id": correlation,
            },
        )

    assert resp.status_code == 202, resp.text
    assert resp.json()["accepted"] == 1
    assert resp.headers["x-correlation-id"] == correlation
    expected = edge_correlation_id(correlation)
    ((_chain, draft),) = audit.drafts
    assert draft.operation == "interaction.capture"
    assert draft.correlation_id == expected
    assert_metadata_only(draft.model_dump(mode="json"))
    (doc,) = store.index_backend.documents.values()
    assert doc["correlation_id"] == expected
    (message,) = publisher.messages
    assert message.data["payload_ref"]["redaction_state"] in ("redacted", "not_required")


async def test_capture_target_failure_is_edge_error_not_500(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("injected target failure")

    monkeypatch.setattr(edge_module, "capture_target_for", broken)
    r = await rig(tmp_path, monkeypatch)
    items = [
        ce(TELEMETRY_TYPE, telemetry_data(f"evt-{i}", domain_id=DOMAIN, prompt=h.canary()), f"c{i}")
        for i in range(2)
    ]

    result = await r.service.ingest_events(r.producer, json.dumps(items).encode(), BATCH)

    assert result.accepted == 2
    assert all(m.data["payload_ref"] is None for m in r.publisher.messages)
    assert r.capture is not None
    assert r.capture.stats.snapshot()["capture_failed"] == {"edge_error": 2}
    assert r.store is not None
    assert r.store.index_backend.documents == {}
    assert r.store.content_backend.blobs == {}


async def test_rejected_span_with_body_does_not_shift_the_next_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = om.map_span

    def with_domain(*args: Any, **kwargs: Any) -> TelemetryEvent:
        event = original(*args, **kwargs)
        return TelemetryEvent.model_validate({**event.model_dump(mode="json"), "domain_id": DOMAIN})

    monkeypatch.setattr(om, "map_span", with_domain)
    r = await rig(tmp_path, monkeypatch)
    first_mark, second_mark = h.canary(), h.canary()
    rejected = h.span("b7ad6b7169203331", {"gen_ai.prompt": f"first {first_mark}"})
    del rejected["startTimeUnixNano"]  # MappingError: missing_time
    accepted = h.span("b7ad6b7169203332", {"gen_ai.prompt": f"second {second_mark}"})

    result = await r.service.ingest_otlp_traces(
        r.producer, json.dumps(h.traces_doc([rejected, accepted])).encode()
    )

    assert result.accepted == 1
    assert [item.index for item in result.rejected] == [0]
    (message,) = r.publisher.messages
    ref = message.data["payload_ref"]
    assert ref is not None
    assert message.data["span_id"] == "b7ad6b7169203332"
    assert r.store is not None
    content = await r.store.read_content(CUSTOMER, DOMAIN, ref["interaction_id"])
    stored = content.model_dump_json()
    assert second_mark in stored
    assert first_mark not in stored
    assert len(r.store.index_backend.documents) == 1
    assert find_body_fields(message.data) == []
    assert first_mark not in message.to_bytes().decode()
    assert second_mark not in message.to_bytes().decode()
