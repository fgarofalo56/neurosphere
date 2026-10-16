from __future__ import annotations

import json

from neurosphere_core.payload import find_body_fields

from .conftest import Harness, span, traces_doc

SENTINEL_PROMPT = "SYNTHETIC-PROMPT-SENTINEL"
SENTINEL_RESPONSE = "SYNTHETIC-RESPONSE-SENTINEL"
JSON = {"content-type": "application/json"}


def test_body_attributes_dropped_at_any_depth_in_otlp(harness: Harness) -> None:
    doc = traces_doc(
        [
            span(
                attrs={
                    "gen_ai.prompt": SENTINEL_PROMPT,
                    "gen_ai.completion": SENTINEL_RESPONSE,
                    "gen_ai.input.messages": SENTINEL_PROMPT,
                    "gen_ai.request.model": "model-x",
                    "gen_ai.usage.input_tokens": 12,
                }
            )
        ],
        {"neurosphere.source_id": "src-synthetic"},
    )
    # Body-like key hidden in a nested structure too (events carry attribute lists).
    doc["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["events"] = [
        {"name": "e", "attributes": [{"key": "prompt", "value": {"stringValue": SENTINEL_PROMPT}}]}
    ]
    resp = harness.client.post(
        "/v1/ingest/otlp/traces", content=json.dumps(doc), headers={**JSON, **harness.auth}
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["accepted"] == 1
    assert body["dropped_fields"] == {
        "gen_ai.prompt": 1,
        "gen_ai.completion": 1,
        "gen_ai.input.messages": 1,
        "prompt": 1,
    }
    # Counts only: no value text anywhere in the response.
    assert SENTINEL_PROMPT not in resp.text
    assert SENTINEL_RESPONSE not in resp.text
    (msg,) = harness.publisher.messages
    raw = msg.to_bytes().decode()
    assert SENTINEL_PROMPT not in raw
    assert SENTINEL_RESPONSE not in raw
    assert find_body_fields(msg.data) == []
    assert msg.data["model"] == "model-x"  # non-body attributes survive


def test_body_fields_dropped_from_cloudevent_data(harness: Harness) -> None:
    event = {
        "specversion": "1.0",
        "id": "ce-1",
        "source": "synthetic",
        "type": "com.neurosphere.telemetry.v1",
        "data": {
            "schema_version": "1.0.0",
            "event_id": "evt-1",
            "event_time": "2026-01-01T00:00:00Z",
            "prompt": SENTINEL_PROMPT,
            "nested": {"response": SENTINEL_RESPONSE},
        },
    }
    resp = harness.client.post(
        "/v1/ingest/events",
        content=json.dumps(event),
        headers={"content-type": "application/cloudevents+json", **harness.auth},
    )
    # Body fields are removed before validation; the leftover unknown member is then rejected
    # individually, so no value can reach the hub either way.
    assert resp.status_code == 202
    assert resp.json()["dropped_fields"] == {"prompt": 1, "response": 1}
    assert SENTINEL_PROMPT not in resp.text
    assert all(SENTINEL_PROMPT not in m.to_bytes().decode() for m in harness.publisher.messages)
