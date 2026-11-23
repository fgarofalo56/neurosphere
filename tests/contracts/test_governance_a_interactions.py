"""Interactions area contracts (PRP-99 item 2).

InteractionRecord, CapturePolicy, InteractionAccessPurpose and InteractionExportManifest.
Rules JSON Schema carries but the generated Pydantic model drops (``not``, if/then) are pinned
here against the JSON Schema itself. Properties are asserted directly; nothing here diffs against
the v1 baseline snapshot.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

import pytest
from contract_support import SCHEMA_ROOT, load_json, load_schema, schema_errors
from neurosphere_core.audit.content_guard import FORBIDDEN_KEYS
from neurosphere_core.payload.guard import is_body_field
from validators import check_kek_uri_cloud

RECORD = "interactions/v1/interaction-record.schema.json"
POLICY = "interactions/v1/capture-policy.schema.json"
PURPOSE = "interactions/v1/interaction-access-purpose.schema.json"
EXPORT = "interactions/v1/interaction-export-manifest.schema.json"
FINDING = "interactions/v1/detection-finding.schema.json"
NEW_SCHEMAS = (RECORD, POLICY, PURPOSE, EXPORT)
VALID = SCHEMA_ROOT / "interactions" / "v1" / "examples" / "valid"


def _walk(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _property_names(rel: str) -> set[str]:
    names: set[str] = set()
    for node in _walk(load_schema(rel)):
        props = node.get("properties")
        if isinstance(props, dict):
            names.update(props)
    return names


def _doc(name: str) -> dict[str, Any]:
    return load_json(VALID / name)


def _policy() -> dict[str, Any]:
    return _doc("capture-policy.active-v2.json")


def _credential_categories() -> list[str]:
    return list(load_schema(FINDING)["$defs"]["credential_category"]["enum"])


def _all_categories() -> list[str]:
    return list(load_schema(FINDING)["$defs"]["detected_category"]["enum"])


# ------------------------------------------------------------------ criterion 4: containment


def test_record_has_no_text_or_body_like_property() -> None:
    names = _property_names(RECORD)
    assert "text" not in names
    assert not {n for n in names if is_body_field(n)}
    assert not names & FORBIDDEN_KEYS


@pytest.mark.parametrize("rel", NEW_SCHEMAS)
def test_new_schemas_carry_no_guarded_property_name(rel: str) -> None:
    names = _property_names(rel)
    assert "text" not in names
    assert not {n for n in names if is_body_field(n)}
    assert not names & FORBIDDEN_KEYS
    for node in _walk(load_schema(rel)):
        props = node.get("properties")
        if isinstance(props, dict):
            assert not {"key", "value"} <= set(props)


@pytest.mark.parametrize("rel", NEW_SCHEMAS)
def test_no_string_longer_than_1024(rel: str) -> None:
    for node in _walk(load_schema(rel)):
        assert node.get("maxLength", 0) <= 1024


@pytest.mark.parametrize("rel", NEW_SCHEMAS)
def test_no_ref_to_content_schemas(rel: str) -> None:
    for node in _walk(load_schema(rel)):
        ref = node.get("$ref")
        if isinstance(ref, str):
            assert "content-envelope" not in ref
            assert "redacted-content" not in ref


def test_record_rejects_prompt_and_text_properties() -> None:
    for name in ("prompt", "response", "text", "body"):
        doc = _doc("interaction-record.findings-content-ref.json")
        doc[name] = "x"
        assert schema_errors(RECORD, doc), name


def test_record_redaction_states() -> None:
    enum = load_schema(RECORD)["properties"]["redaction_state"]["enum"]
    assert enum == ["redacted", "not_required", "redaction_failed"]
    doc = _doc("interaction-record.findings-content-ref.json")
    doc["redaction_state"] = "pending"
    assert schema_errors(RECORD, doc)


def test_record_content_ref_and_pointer_bound() -> None:
    doc = _doc("interaction-record.findings-content-ref.json")
    doc["content_ref"]["pointer"] = "p" * 1025
    assert schema_errors(RECORD, doc)
    doc["content_ref"]["pointer"] = "p" * 1024
    assert not schema_errors(RECORD, doc)
    doc["content_ref"]["plaintext_sha256"] = "a" * 64
    assert schema_errors(RECORD, doc)


def test_record_uses_catalog_sensitivity_category() -> None:
    doc = _doc("interaction-record.findings-content-ref.json")
    doc["sensitivity_categories"] = ["not_a_category"]
    assert schema_errors(RECORD, doc)


def test_record_defaults() -> None:
    props = load_schema(RECORD)["properties"]
    assert props["retention_class"]["default"] == "interaction_default"
    assert props["legal_hold_ids"]["default"] == []
    assert props["legal_hold_ids"]["maxItems"] == 16
    assert props["data_asset_ids"]["maxItems"] == 50
    assert props["findings_summary"]["maxItems"] == 64


def test_encrypted_object_ref_is_shared() -> None:
    export = load_schema(EXPORT)["properties"]["bundle"]
    assert export["$ref"] == "interaction-record.schema.json#/$defs/encrypted_object_ref"
    ref = load_schema(RECORD)["$defs"]["encrypted_object_ref"]
    assert ref["properties"]["algorithm"] == {
        "description": ref["properties"]["algorithm"]["description"],
        "const": "aes_256_gcm",
    }


# ------------------------------------------------------------------ kek_uri


def test_kek_uri_accepts_key_vault_identifiers_only() -> None:
    doc = _doc("interaction-record.findings-content-ref.json")
    good = [
        "https://acme-kv.vault.azure.net/keys/ns-content-kek",
        "https://acme-kv.vault.azure.net/keys/ns-content-kek/" + "0" * 32,
        "https://acme-kv.vault.usgovcloudapi.net/keys/k1",
    ]
    bad = [
        "https://example.com/keys/k1",
        "http://acme-kv.vault.azure.net/keys/k1",
        "https://acme-kv.vault.azure.net/secrets/k1",
        "https://user@acme-kv.vault.azure.net/keys/k1",
        "https://acme-kv.vault.azure.net/keys/k1?x=1",
        "https://acme-kv.vault.azure.net.evil.test/keys/k1",
    ]
    for uri in good:
        doc["content_ref"]["kek_uri"] = uri
        assert not schema_errors(RECORD, doc), uri
    for uri in bad:
        doc["content_ref"]["kek_uri"] = uri
        assert schema_errors(RECORD, doc), uri


def test_check_kek_uri_cloud() -> None:
    commercial = "https://acme-kv.vault.azure.net/keys/k1"
    government = "https://acme-kv.vault.usgovcloudapi.net/keys/k1"
    assert check_kek_uri_cloud(commercial, "commercial") == []
    assert check_kek_uri_cloud(government, "government") == []
    assert check_kek_uri_cloud(government, "commercial")
    assert check_kek_uri_cloud(commercial, "government")
    assert check_kek_uri_cloud(commercial, "mars")
    host = urlsplit(government).hostname or ""
    assert host.split(".")[-3:] == ["vault", "usgovcloudapi", "net"]


# ------------------------------------------------------------------ capture policy


@pytest.mark.parametrize("category", _credential_categories())
def test_policy_rejects_each_credential_category_in_kept(category: str) -> None:
    doc = _policy()
    doc["kept_categories"] = [category]
    assert schema_errors(POLICY, doc)


def test_policy_credential_categories_cover_the_first_eight() -> None:
    assert _credential_categories() == _all_categories()[:8]
    assert "jwt" in _credential_categories()


def test_policy_accepts_non_credential_kept_categories() -> None:
    doc = _policy()
    doc["kept_categories"] = ["email_address", "guid"]
    assert not schema_errors(POLICY, doc)
    doc["kept_categories"] = ["email_address", "email_address"]
    assert schema_errors(POLICY, doc)


@pytest.mark.parametrize("missing", ["approved_intent_id", "approved_audit_id"])
def test_active_policy_requires_approval_ids(missing: str) -> None:
    doc = _policy()
    del doc[missing]
    assert schema_errors(POLICY, doc)
    doc[missing] = None
    assert schema_errors(POLICY, doc)


def test_proposed_policy_needs_no_approval_ids() -> None:
    doc = _doc("capture-policy.proposed.json")
    assert doc["state"] == "proposed"
    assert not schema_errors(POLICY, doc)
    for key in ("approved_intent_id", "approved_audit_id", "effective_from"):
        del doc[key]
    assert not schema_errors(POLICY, doc)


def test_policy_defaults_follow_the_owner_decisions() -> None:
    props = load_schema(POLICY)["properties"]
    assert props["redaction_mode"]["default"] == "redact_all_detections"
    assert props["redaction_mode"]["enum"] == ["redact_all_detections", "redact_listed"]
    assert props["retention_days"]["default"] == 90
    assert (props["retention_days"]["minimum"], props["retention_days"]["maximum"]) == (1, 365)
    assert props["max_part_chars"]["default"] == 8192
    assert (props["max_part_chars"]["minimum"], props["max_part_chars"]["maximum"]) == (1, 32768)
    assert props["kept_categories"]["default"] == []
    assert props["customer_dictionary_ids"]["default"] == []


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("retention_days",), 0),
        (("retention_days",), 366),
        (("max_part_chars",), 0),
        (("max_part_chars",), 32769),
        (("sampling", "rate"), 0),
        (("sampling", "rate"), 1.01),
        (("sampling", "max_per_minute"), 6001),
        (("state",), "pending"),
        (("version",), 0),
        (("source_ids",), []),
        (("parts",), []),
        (("redaction_mode",), "keep_everything"),
    ],
)
def test_policy_bounds(path: tuple[str, ...], value: Any) -> None:
    doc = copy.deepcopy(_policy())
    node = doc
    for step in path[:-1]:
        node = node[step]
    node[path[-1]] = value
    assert schema_errors(POLICY, doc)


def test_policy_sampling_rate_of_one_is_allowed() -> None:
    doc = _policy()
    doc["sampling"]["rate"] = 1
    assert not schema_errors(POLICY, doc)


# ------------------------------------------------------------------ purpose and export


def test_access_purpose_rejects_unknown_keys() -> None:
    doc = _doc("interaction-access-purpose.incident.json")
    assert not schema_errors(PURPOSE, doc)
    doc["note"] = "free text"
    assert schema_errors(PURPOSE, doc)


def test_access_purpose_is_a_fragment_and_open_ended() -> None:
    schema = load_schema(PURPOSE)
    assert "schema_version" not in schema["properties"]
    assert (
        "open-ended: readers must tolerate unknown values"
        in (schema["properties"]["purpose_code"]["description"])
    )
    doc = _doc("interaction-access-purpose.incident.json")
    doc["case_ref"] = None
    assert not schema_errors(PURPOSE, doc)


def test_export_manifest_interaction_ids_max_1000() -> None:
    doc = _doc("interaction-export-manifest.incident.json")
    one = doc["interaction_ids"][0]
    doc["interaction_ids"] = [one] * 1000
    assert not schema_errors(EXPORT, doc)
    doc["interaction_ids"] = [one] * 1001
    assert schema_errors(EXPORT, doc)


def test_export_manifest_purpose_and_bundle_are_strict() -> None:
    doc = _doc("interaction-export-manifest.incident.json")
    doc["purpose"]["note"] = "x"
    assert schema_errors(EXPORT, doc)
    doc = _doc("interaction-export-manifest.incident.json")
    doc["bundle"]["algorithm"] = "none"
    assert schema_errors(EXPORT, doc)
    doc = _doc("interaction-export-manifest.incident.json")
    doc["domain_ids"] = []
    assert schema_errors(EXPORT, doc)
