from typing import Any

import pytest
from neurosphere_core.payload import (
    CLOUDEVENT_TYPE_COST,
    CLOUDEVENT_TYPE_TELEMETRY,
    REQUEST_ID_EXTENSION,
    HubMessage,
    HubMessageKind,
)
from pydantic import ValidationError


def _fields(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": HubMessageKind.TELEMETRY,
        "event_id": "evt-1",
        "cloud": "commercial",
        "customer_id": "cust-1",
        "source_id": "src-1",
        "producer_id": "prod-1",
        "received_at": "2026-01-01T00:00:00Z",
        "data": {"model": "m", "attrs": [{"key": "ok", "value": {"intValue": 1}}]},
    }
    base.update(over)
    return base


def test_constants() -> None:
    assert CLOUDEVENT_TYPE_TELEMETRY == "com.neurosphere.telemetry.v1"
    assert CLOUDEVENT_TYPE_COST == "com.neurosphere.cost.v1"
    assert REQUEST_ID_EXTENSION == "nsrequestid"


def test_round_trip() -> None:
    msg = HubMessage(
        **_fields(request_id="r1", observation_kind="gateway", dropped_field_counts={"prompt": 2})
    )
    raw = msg.to_bytes()
    assert b" " not in raw.replace(b"2026", b"")  # compact separators
    back = HubMessage.from_bytes(raw)
    assert back == msg
    assert back.wire_version == "1"
    assert back.kind is HubMessageKind.TELEMETRY
    assert back.observation_kind == "gateway"
    assert HubMessage(**_fields()).observation_kind is None
    with pytest.raises(ValidationError):
        HubMessage(**_fields(observation_kind="bogus"))


def test_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        HubMessage(**_fields(unexpected=1))


def test_body_field_in_data_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        HubMessage(**_fields(data={"a": {"prompt": "fake-secret-0000"}}))
    assert "fake-secret-0000" not in str(exc.value)
    with pytest.raises(ValidationError):
        HubMessage(**_fields(data={"attrs": [{"key": "gen_ai.prompt", "value": {}}]}))


def test_empty_and_long_ids_rejected() -> None:
    with pytest.raises(ValidationError):
        HubMessage(**_fields(event_id=""))
    with pytest.raises(ValidationError):
        HubMessage(**_fields(customer_id="x" * 257))


def test_keys() -> None:
    msg = HubMessage(**_fields())
    assert msg.partition_key() == "cust-1|src-1"
    assert msg.dedupe_key() == ("cust-1", "src-1", "evt-1")


def test_frozen() -> None:
    msg = HubMessage(**_fields())
    with pytest.raises(ValidationError):
        msg.event_id = "other"  # type: ignore[misc]


def test_deep_raw_bytes_rejected_before_parse() -> None:
    raw = b'{"data":' + b"[" * 100_000 + b"]" * 100_000 + b"}"
    with pytest.raises(ValueError, match="depth"):
        HubMessage.from_bytes(raw)
