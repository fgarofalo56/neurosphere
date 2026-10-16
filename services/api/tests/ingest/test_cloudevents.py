from __future__ import annotations

import json
from typing import Any

from neurosphere_core.payload import (
    CLOUDEVENT_TYPE_COST,
    CLOUDEVENT_TYPE_TELEMETRY,
    REQUEST_ID_EXTENSION,
)

from .conftest import CUSTOMER, SOURCE, Harness

STRUCTURED = "application/cloudevents+json"
BATCH = "application/cloudevents-batch+json"


def telemetry_data(event_id: str, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "event_id": event_id,
        "event_time": "2026-01-01T00:00:00Z",
        "cloud": "commercial",
        "customer_id": CUSTOMER,
        "source_id": SOURCE,
        "request_id": "req-9",
        **extra,
    }


def cost_data(cost_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "cost_id": cost_id,
        "kind": "estimated",
        "amount": "1.25",
        "currency": "USD",
        "price_version": "price-synthetic-1",
        "price_effective_date": "2026-01-01",
        "cloud": "commercial",
        "customer_id": CUSTOMER,
        "source_id": SOURCE,
        "dedupe_key": "dk-1",
        "observation_source": "application",
        "recorded_at": "2026-01-01T00:00:00Z",
    }


def ce(type_: str, data: Any, ce_id: str = "ce-1", **ext: Any) -> dict[str, Any]:
    return {
        "specversion": "1.0",
        "id": ce_id,
        "source": "synthetic/producer",
        "type": type_,
        "datacontenttype": "application/json",
        "data": data,
        **ext,
    }


def send(h: Harness, body: Any, content_type: str):
    return h.client.post(
        "/v1/ingest/events",
        content=json.dumps(body),
        headers={"content-type": content_type, **h.auth},
    )


def test_structured_telemetry(harness: Harness) -> None:
    resp = send(harness, ce(CLOUDEVENT_TYPE_TELEMETRY, telemetry_data("evt-1")), STRUCTURED)
    assert resp.status_code == 202
    assert resp.json() == {"accepted": 1, "rejected": [], "ignored": [], "dropped_fields": {}}
    (msg,) = harness.publisher.messages
    assert msg.kind == "telemetry"
    assert msg.event_id == "evt-1"
    assert msg.request_id == "req-9"
    assert msg.data["ingestion_time"] == msg.received_at
    assert msg.partition_key() == f"{CUSTOMER}|{SOURCE}"


def test_batch_partial_success_with_per_index_reasons(harness: Harness) -> None:
    bad_schema = telemetry_data("evt-bad")
    del bad_schema["event_time"]
    batch = [
        ce(CLOUDEVENT_TYPE_TELEMETRY, telemetry_data("evt-1"), "ce-1"),
        ce(CLOUDEVENT_TYPE_TELEMETRY, bad_schema, "ce-2"),
        {"specversion": "1.0", "id": "ce-3", "type": CLOUDEVENT_TYPE_TELEMETRY},  # no source
        ce("com.example.other", {}, "ce-4"),
        ce(CLOUDEVENT_TYPE_TELEMETRY, telemetry_data("evt-5"), "ce-5"),
        "not-an-object",
    ]
    resp = send(harness, batch, BATCH)
    assert resp.status_code == 202
    body = resp.json()
    assert body["accepted"] == 2
    assert body["rejected"] == [
        {"index": 1, "reason_code": "invalid_event"},
        {"index": 2, "reason_code": "invalid_cloudevent"},
        {"index": 3, "reason_code": "unsupported_event_type"},
        {"index": 5, "reason_code": "invalid_cloudevent"},
    ]
    assert [m.event_id for m in harness.publisher.messages] == ["evt-1", "evt-5"]


def test_cost_event_with_request_id_extension(harness: Harness) -> None:
    event = ce(CLOUDEVENT_TYPE_COST, cost_data("cost-1"), **{REQUEST_ID_EXTENSION: "req-77"})
    resp = send(harness, event, STRUCTURED)
    assert resp.status_code == 202
    (msg,) = harness.publisher.messages
    assert msg.kind == "cost"
    assert msg.event_id == "cost-1"
    assert msg.request_id == "req-77"
    assert msg.observation_kind == "application"
    assert msg.data["amount"] == "1.25"


def test_cost_observation_source_mismatch_is_403(harness: Harness) -> None:
    data = cost_data("cost-2")
    data["observation_source"] = "billing"
    resp = send(harness, ce(CLOUDEVENT_TYPE_COST, data), STRUCTURED)
    assert resp.status_code == 403
    assert harness.publisher.messages == []


def test_claim_mismatch_in_batch_publishes_nothing(harness: Harness) -> None:
    batch = [
        ce(CLOUDEVENT_TYPE_TELEMETRY, telemetry_data("evt-1"), "ce-1"),
        ce(CLOUDEVENT_TYPE_TELEMETRY, telemetry_data("evt-2", customer_id="other"), "ce-2"),
    ]
    resp = send(harness, batch, BATCH)
    assert resp.status_code == 403
    assert harness.publisher.messages == []


def test_media_type_and_shape_errors(harness: Harness) -> None:
    wrong = send(harness, {}, "application/json")
    assert wrong.status_code == 422
    assert wrong.json()["reason"] == "unsupported_media_type"
    not_list = send(harness, ce(CLOUDEVENT_TYPE_TELEMETRY, {}), BATCH)
    assert not_list.json()["reason"] == "invalid_envelope"
    not_obj = send(harness, [], STRUCTURED)
    assert not_obj.json()["reason"] == "invalid_envelope"
