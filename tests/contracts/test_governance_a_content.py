"""Opt-in content channel contracts (PRP-99 item 1).

ContentEnvelope, RedactedContent, DetectionFinding and the metadata-only ``payload_ref``
extensions. Rules JSON Schema carries but the generated Pydantic model drops (``not``,
``if/then``, ``uniqueItems``) are pinned here against the JSON Schema itself. Every
secret-shaped string is assembled at runtime so no literal that looks like a key, JWT or token
is committed (gitleaks scans full history).
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from contract_support import SCHEMA_ROOT, load_json, load_schema, schema_errors
from validators import (
    SECRET_TEXT_PATTERNS,
    check_content_envelope_parts,
    check_secret_free_text,
)

ENVELOPE = "telemetry/v1/content-envelope.schema.json"
EVENT = "telemetry/v1/telemetry-event.schema.json"
REDACTED = "interactions/v1/redacted-content.schema.json"
FINDING = "interactions/v1/detection-finding.schema.json"
TELEMETRY_EXAMPLES = SCHEMA_ROOT / "telemetry" / "v1" / "examples" / "valid"
INTERACTION_EXAMPLES = SCHEMA_ROOT / "interactions" / "v1" / "examples" / "valid"

KINDS = ("prompt", "response", "tool_input", "tool_output", "system_instructions")


def _secret_samples() -> dict[str, str]:
    """One sample per credential format, built from fragments."""
    return {
        "private key block": "-----BEGIN RSA PRIVATE " + "KEY-----",
        "JWT": "ey" + "JhbGciOiJIUzI1NiJ9" + "." + "ey" + "JzdWIiOiIxIn0" + "." + "abcdefgh1234",
        "bearer token": "Bear" + "er " + "a1b2c3d4e5f6g7h8",
        "AWS access key id": "AK" + "IA" + "X" * 16,
        "GitHub token": "gh" + "p_" + "a1B2" * 9,
        "sk- key": "s" + "k-" + "Ab12" * 6,
        "Azure storage or Service Bus key assignment": (
            "Endpoint=sb://x;Shared" + "AccessKey" + "=" + "Zm9vYmFy" * 3
        ),
        "SAS signature": "https://h/x?s" + "ig=" + "Ab12%2B" * 5,
        "URL with userinfo": "post" + "gres://" + "admin" + ":" + "hunter2" + "@db.local/x",
    }


def _redacted(text: str) -> dict[str, Any]:
    doc = load_json(INTERACTION_EXAMPLES / "redacted-content.jwt-placeholder.json")
    doc["parts"][0]["text"] = text
    return doc


def _envelope() -> dict[str, Any]:
    return load_json(TELEMETRY_EXAMPLES / "content-envelope.prompt-response.json")


# ------------------------------------------------------------------ secret-free text


def test_samples_cover_every_listed_format() -> None:
    assert set(_secret_samples()) == set(SECRET_TEXT_PATTERNS)


@pytest.mark.parametrize("name", sorted(_secret_samples()))
def test_each_credential_format_is_rejected_in_text(name: str) -> None:
    sample = _secret_samples()[name]
    text = f"before {sample} after"
    assert schema_errors(REDACTED, _redacted(text)), name
    assert f"text contains a {name}" in check_secret_free_text(text), name


def test_asia_and_other_github_prefixes_are_rejected() -> None:
    for text in (
        "AS" + "IA" + "Y" * 16,
        "gh" + "o_" + "x1" * 12,
        "gh" + "u_" + "x1" * 12,
        "gh" + "s_" + "x1" * 12,
        "gh" + "r_" + "x1" * 12,
        "github" + "_pat_" + "x1" * 14,
    ):
        assert check_secret_free_text(text), text
        assert schema_errors(REDACTED, _redacted(text)), text


def test_placeholder_and_plain_text_are_accepted() -> None:
    for text in (
        "token [[ns-redacted:jwt]] done",
        "Bearer [[ns-redacted:bearer_token]]",
        "Account" + "Key=[[ns-redacted:connection_string]]",
        "",
        "Plain sentence about invoices. Email [[ns-redacted:email_address]].",
    ):
        assert not schema_errors(REDACTED, _redacted(text)), text
        assert check_secret_free_text(text) == [], text


def test_python_mirror_equals_the_schema_patterns() -> None:
    schema = load_schema(REDACTED)
    branches = schema["$defs"]["secret_free_text"]["not"]["anyOf"]
    assert [b["pattern"] for b in branches] == list(SECRET_TEXT_PATTERNS.values())


def test_redacted_content_state_is_closed() -> None:
    schema = load_schema(REDACTED)
    assert schema["properties"]["redaction_state"]["enum"] == ["redacted", "not_required"]
    for state in ("pending", "redaction_failed", "unknown"):
        doc = _redacted("ok")
        doc["redaction_state"] = state
        assert schema_errors(REDACTED, doc), state


def test_secret_free_text_length_bounds() -> None:
    assert not schema_errors(REDACTED, _redacted("a" * 32768))
    assert schema_errors(REDACTED, _redacted("a" * 32769))


# ------------------------------------------------------------------ detection finding


def test_credential_finding_must_be_replaced() -> None:
    finding = load_json(INTERACTION_EXAMPLES / "detection-finding.jwt-replaced.json")
    assert not schema_errors(FINDING, finding)
    kept = copy.deepcopy(finding)
    kept["action"] = "kept"
    assert schema_errors(FINDING, kept)
    # a non-credential category may be kept
    kept["category"] = "email_address"
    assert not schema_errors(FINDING, kept)


def test_finding_inside_redacted_content_is_checked_too() -> None:
    doc = _redacted("token [[ns-redacted:jwt]]")
    doc["parts"][0]["findings"][0]["action"] = "kept"
    assert schema_errors(REDACTED, doc)


def test_every_credential_category_is_a_detected_category() -> None:
    defs = load_schema(FINDING)["$defs"]
    credential = defs["credential_category"]["enum"]
    detected = defs["detected_category"]["enum"]
    assert len(credential) == 8
    assert detected[:8] == credential
    assert set(credential) <= set(detected)
    assert (
        "open-ended: readers must tolerate unknown values"
        in (defs["detected_category"]["description"])
    )
    assert defs["part_kind"]["enum"] == list(KINDS)


# ------------------------------------------------------------------ content envelope


def test_envelope_example_is_valid_and_has_one_part_per_kind() -> None:
    doc = _envelope()
    assert not schema_errors(ENVELOPE, doc)
    assert check_content_envelope_parts(doc) == []


def test_envelope_rejects_duplicate_part_kinds_by_validator() -> None:
    doc = _envelope()
    doc["parts"].append({"part": "prompt", "text": "again"})
    assert check_content_envelope_parts(doc) == ["duplicate content part kind 'prompt'"]


def test_envelope_bounds() -> None:
    doc = _envelope()
    doc["parts"] = []
    assert schema_errors(ENVELOPE, doc)
    doc["parts"] = [{"part": k, "text": "x"} for k in KINDS]
    assert not schema_errors(ENVELOPE, doc)
    doc["parts"].append({"part": "prompt", "text": "x"})
    assert schema_errors(ENVELOPE, doc)
    for text, ok in (("", False), ("a" * 32768, True), ("a" * 32769, False)):
        doc = _envelope()
        doc["parts"] = [{"part": "prompt", "text": text}]
        assert (not schema_errors(ENVELOPE, doc)) is ok, len(text)


def test_envelope_text_forbids_control_characters_except_tab_cr_lf() -> None:
    for char in ("\t", "\r", "\n"):
        doc = _envelope()
        doc["parts"] = [{"part": "prompt", "text": f"a{char}b"}]
        assert not schema_errors(ENVELOPE, doc), repr(char)
    for code in (0, 1, 8, 11, 12, 14, 31, 127):
        doc = _envelope()
        doc["parts"] = [{"part": "prompt", "text": f"a{chr(code)}b"}]
        assert schema_errors(ENVELOPE, doc), code


def test_envelope_truncated_defaults_false_and_extra_keys_are_rejected() -> None:
    props = load_schema(ENVELOPE)["$defs"]["content_part"]["properties"]
    assert props["truncated"]["default"] is False
    doc = _envelope()
    doc["authorization"] = "x"
    assert schema_errors(ENVELOPE, doc)
    doc = _envelope()
    doc["parts"][0]["role"] = "user"
    assert schema_errors(ENVELOPE, doc)


# ------------------------------------------------------------------ payload_ref


def _payload_ref(doc: dict[str, Any]) -> dict[str, Any]:
    return doc["payload_ref"]


def test_payload_ref_new_members_validate_and_have_bounds() -> None:
    doc = load_json(TELEMETRY_EXAMPLES / "telemetry-event.payload-ref-capture.json")
    assert not schema_errors(EVENT, doc)
    bad = copy.deepcopy(doc)
    _payload_ref(bad)["capture_policy_version"] = 0
    assert schema_errors(EVENT, bad)
    bad = copy.deepcopy(doc)
    _payload_ref(bad)["interaction_id"] = "NOT-A-UUID"
    assert schema_errors(EVENT, bad)
    bad = copy.deepcopy(doc)
    _payload_ref(bad)["detected_categories"] = ["jwt", "jwt"]
    assert schema_errors(EVENT, bad)
    bad = copy.deepcopy(doc)
    _payload_ref(bad)["content_parts"] = [
        {"part": "prompt", "char_count": 1, "truncated": False}
    ] * 6
    assert schema_errors(EVENT, bad)
    bad = copy.deepcopy(doc)
    _payload_ref(bad)["content_parts"][0]["text"] = "body"
    assert schema_errors(EVENT, bad)
    bad = copy.deepcopy(doc)
    _payload_ref(bad)["body"] = "x"
    assert schema_errors(EVENT, bad)


def test_payload_ref_adds_no_top_level_property_and_keeps_redaction_state() -> None:
    schema = load_schema(EVENT)
    props = schema["$defs"]["payload_ref"]["properties"]
    assert set(props) == {
        "pointer",
        "classification",
        "redaction_state",
        "interaction_id",
        "capture_policy_id",
        "capture_policy_version",
        "detector_set_version",
        "detected_categories",
        "content_parts",
    }
    assert props["redaction_state"]["enum"] == [
        "redacted",
        "pending",
        "redaction_failed",
        "not_required",
        "unknown",
    ]
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["payload_ref"]["additionalProperties"] is False
    assert "payload_ref" in schema["properties"]
    assert not {"parts", "text", "content", "content_parts"} & set(schema["properties"])


def test_events_written_before_the_content_channel_still_validate() -> None:
    old = [
        p
        for p in sorted(TELEMETRY_EXAMPLES.glob("telemetry-event.*.json"))
        if load_json(p)["schema_version"] != "1.2.0"
    ]
    assert old
    for path in old:
        doc = load_json(path)
        assert not schema_errors(EVENT, doc), path.name
        assert "interaction_id" not in (doc.get("payload_ref") or {})
