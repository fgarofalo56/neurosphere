"""PRP-70 item 7 (fold F1): tool, service and MCP-server identity on the telemetry event.

JSON Schema is the source of truth. The Pydantic generator drops ``minProperties``, so the
empty-object rule is a JSON Schema check only (it is also an example file, which the roundtrip
test projects away); every other rule is checked against both.
"""

from __future__ import annotations

import copy
from typing import Any

import pydantic
import pytest
from contract_support import FIXTURES_DIR, SCHEMA_ROOT, load_json, model_for, schema_errors

REL = "telemetry/v1/telemetry-event.schema.json"
EXAMPLES = SCHEMA_ROOT / "telemetry" / "v1" / "examples" / "valid"
BASELINE = FIXTURES_DIR / "v1-baseline" / "telemetry" / "v1" / "telemetry-event.schema.json"

CANON_TOOL = "commercial:contoso:otel-gateway-01:tool:lookup-invoice"


def _event() -> dict[str, Any]:
    return copy.deepcopy(load_json(EXAMPLES / "telemetry-event.tool-service-mcp.json"))


def _accepted(doc: dict[str, Any]) -> None:
    assert schema_errors(REL, doc) == []
    model_for(REL).model_validate(doc)


def _rejected_by_both(doc: dict[str, Any]) -> None:
    assert schema_errors(REL, doc)
    with pytest.raises(pydantic.ValidationError):
        model_for(REL).model_validate(doc)


def test_event_with_tool_service_and_mcp_validates() -> None:
    event = _event()
    assert set(event["tool"]) == {"external_tool_id", "canonical_tool_id", "tool_name"}
    assert set(event["service"]) == {"external_service_id", "canonical_service_id"}
    assert event["mcp_server_ref"]
    _accepted(event)


def test_existing_examples_unchanged_and_default_to_none() -> None:
    model = model_for(REL)
    for name in (
        "telemetry-event.full-model-call.json",
        "telemetry-event.minimal-all-unknown.json",
    ):
        doc = load_json(EXAMPLES / name)
        assert "tool" not in doc
        assert schema_errors(REL, doc) == []
        parsed = model.model_validate(doc)
        assert parsed.tool is None
        assert parsed.service is None
        assert parsed.mcp_server_ref is None


@pytest.mark.parametrize("field", ["tool", "service", "mcp_server_ref"])
def test_null_accepted(field: str) -> None:
    event = _event()
    event[field] = None
    _accepted(event)


@pytest.mark.parametrize("field", ["tool", "service"])
def test_empty_object_rejected_by_json_schema(field: str) -> None:
    event = _event()
    event[field] = {}
    errors = schema_errors(REL, event)
    assert errors
    assert any(e.validator == "minProperties" for e in _flatten(errors))


def _flatten(errors: list[Any]) -> list[Any]:
    out: list[Any] = []
    for err in errors:
        out.append(err)
        out.extend(_flatten(list(err.context or [])))
    return out


@pytest.mark.parametrize("field", ["tool", "service"])
def test_all_null_members_accepted(field: str) -> None:
    # minProperties counts keys, so an explicit all-null object is a present member set.
    event = _event()
    event[field] = {key: None for key in event[field]}
    _accepted(event)


@pytest.mark.parametrize("field", ["tool", "service"])
def test_unknown_key_rejected(field: str) -> None:
    event = _event()
    event[field]["prompt"] = "x"
    _rejected_by_both(event)


@pytest.mark.parametrize(
    ("field", "member", "value"),
    [
        ("tool", "external_tool_id", "a" * 257),
        ("tool", "tool_name", "a" * 129),
        ("tool", "canonical_tool_id", "commercial:c:s:tool:" + "a" * 500),
        ("service", "external_service_id", "a" * 257),
        ("service", "canonical_service_id", "commercial:c:s:service:" + "a" * 500),
        ("tool", "external_tool_id", ""),
    ],
)
def test_member_over_cap_rejected(field: str, member: str, value: str) -> None:
    event = _event()
    event[field][member] = value
    _rejected_by_both(event)


def test_canonical_member_must_be_canonical_id() -> None:
    event = _event()
    event["tool"]["canonical_tool_id"] = "Not A Canonical Id"
    _rejected_by_both(event)


@pytest.mark.parametrize("value", ["a" * 513, ""])
def test_mcp_server_ref_bad_length_rejected(value: str) -> None:
    event = _event()
    event["mcp_server_ref"] = value
    _rejected_by_both(event)


def test_mcp_server_ref_at_cap_accepted() -> None:
    event = _event()
    event["mcp_server_ref"] = "a" * 512
    _accepted(event)


def test_identity_properties_are_optional_and_default_to_null() -> None:
    # Not a diff against the v1 baseline: the snapshot is refreshed once a change is accepted
    # (ADR-0004), after which it already contains these properties.
    current = load_json(SCHEMA_ROOT / REL)
    identity = {"tool", "service", "mcp_server_ref"}
    assert identity <= set(current["properties"])
    assert not identity & set(current["required"])
    assert set(load_json(BASELINE)["required"]) == set(current["required"])
    for name in identity:
        assert current["properties"][name]["default"] is None


def test_payload_ref_untouched() -> None:
    current = load_json(SCHEMA_ROOT / REL)
    baseline = load_json(BASELINE)
    assert current["$defs"]["payload_ref"] == baseline["$defs"]["payload_ref"]
    assert current["properties"]["payload_ref"] == baseline["properties"]["payload_ref"]


def test_new_defs_carry_no_body_like_member() -> None:
    defs = load_json(SCHEMA_ROOT / REL)["$defs"]
    members = set(defs["tool_identity"]["properties"]) | set(defs["service_identity"]["properties"])
    assert members == {
        "external_tool_id",
        "canonical_tool_id",
        "tool_name",
        "external_service_id",
        "canonical_service_id",
    }
    assert defs["tool_identity"]["additionalProperties"] is False
    assert defs["service_identity"]["additionalProperties"] is False
