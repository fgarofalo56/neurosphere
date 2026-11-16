from __future__ import annotations

from typing import Any

from neurosphere_core.payload import CLOUDEVENT_TYPE_COST, CLOUDEVENT_TYPE_TELEMETRY

from .conftest import Harness
from .test_cloudevents import STRUCTURED, ce, cost_data, send, telemetry_data


def _post(h: Harness, type_: str, data: dict[str, Any], **ext: Any) -> Any:
    return send(h, ce(type_, data, **ext), STRUCTURED)


def test_cost_extension_lands_in_tags_and_message(harness: Harness) -> None:
    resp = _post(harness, CLOUDEVENT_TYPE_COST, cost_data("c1"), nscostcenter="CC-4410")
    assert resp.status_code == 202
    (msg,) = harness.publisher.messages
    assert msg.cost_center == "CC-4410"
    assert msg.data["tags"]["cost_center"] == "CC-4410"


def test_telemetry_extension_sets_message_field(harness: Harness) -> None:
    _post(harness, CLOUDEVENT_TYPE_TELEMETRY, telemetry_data("e1"), nscostcenter="CC-1")
    (msg,) = harness.publisher.messages
    assert msg.cost_center == "CC-1"


def test_invalid_or_absent_values_never_reject(harness: Harness) -> None:
    for i, bad in enumerate(["N/A", "", "has space", "x" * 200, 5]):
        resp = _post(harness, CLOUDEVENT_TYPE_COST, cost_data(f"c{i}"), nscostcenter=bad)
        assert resp.json()["accepted"] == 1
    assert all(m.cost_center is None for m in harness.publisher.messages)
    assert all(not m.data.get("tags") for m in harness.publisher.messages)


def test_control_characters_are_stripped(harness: Harness) -> None:
    _post(harness, CLOUDEVENT_TYPE_COST, cost_data("c1"), nscostcenter="CC\x00-1\n")
    (msg,) = harness.publisher.messages
    assert msg.cost_center == "CC-1"


def test_record_tag_wins_and_mismatch_is_counted(harness: Harness) -> None:
    data = cost_data("c1")
    data["tags"] = {"cost_center": "OWN-1"}
    resp = _post(harness, CLOUDEVENT_TYPE_COST, data, nscostcenter="OTHER-2")
    assert resp.json()["accepted"] == 1
    (msg,) = harness.publisher.messages
    assert msg.data["tags"]["cost_center"] == "OWN-1"
    assert msg.cost_center == "OWN-1"
