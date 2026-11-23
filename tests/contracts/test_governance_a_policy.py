"""Policy area contracts (PRP-99 item 3).

PolicyDefinition, PolicyViolation, PolicyException, PolicyDecisionRequest,
PolicyDecisionResponse and EnforcementBinding. Rules JSON Schema carries but the generated
Pydantic model drops (if/then) are pinned here against the JSON Schema itself. Properties are
asserted directly; nothing here diffs against the v1 baseline snapshot.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from typing import Any

import pytest
from contract_support import SCHEMA_ROOT, load_json, load_schema, schema_errors
from neurosphere_core.audit.content_guard import FORBIDDEN_KEYS
from neurosphere_core.payload.guard import is_body_field
from validators import check_decision_request_subject, check_policy_exception_window

DEFINITION = "policy/v1/policy-definition.schema.json"
VIOLATION = "policy/v1/policy-violation.schema.json"
EXCEPTION = "policy/v1/policy-exception.schema.json"
REQUEST = "policy/v1/policy-decision-request.schema.json"
RESPONSE = "policy/v1/policy-decision-response.schema.json"
BINDING = "policy/v1/enforcement-binding.schema.json"
ALL_SCHEMAS = (DEFINITION, VIOLATION, EXCEPTION, REQUEST, RESPONSE, BINDING)
VALID = SCHEMA_ROOT / "policy" / "v1" / "examples" / "valid"

KINDS = {
    "model_allow_list": "ModelAllowListParams",
    "data_sensitivity_access": "DataSensitivityAccessParams",
    "residency": "ResidencyParams",
    "budget": "BudgetRuleParams",
    "required_owner": "RequiredOwnerParams",
    "required_attestation": "RequiredAttestationParams",
    "required_approval": "RequiredApprovalParams",
    "content_rule": "ContentRuleParams",
    "registration_required": "RegistrationRequiredParams",
}


def _walk(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _doc(name: str) -> dict[str, Any]:
    return copy.deepcopy(load_json(VALID / name))


def _definition() -> dict[str, Any]:
    return _doc("policy-definition.all-kinds.json")


def _request() -> dict[str, Any]:
    return _doc("policy-decision-request.model-call.json")


def _exception() -> dict[str, Any]:
    return _doc("policy-exception.approved.json")


def _rule_for(doc: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(r for r in doc["rules"] if r["kind"] == kind)


def _errors(rel: str, doc: dict[str, Any]) -> list[Any]:
    return list(schema_errors(rel, doc))


# ------------------------------------------------------------------ criterion 7: typed rules


def test_examples_cover_each_kind_once() -> None:
    doc = _definition()
    assert [r["kind"] for r in doc["rules"]] == list(KINDS)
    assert not _errors(DEFINITION, doc)


@pytest.mark.parametrize("rel", ALL_SCHEMAS)
def test_valid_examples_validate(rel: str) -> None:
    prefix = rel.rsplit("/", 1)[1].removesuffix(".schema.json")
    files = sorted(VALID.glob(f"{prefix}.*.json"))
    assert files
    for file in files:
        assert not _errors(rel, load_json(file)), file.name


def test_params_titles_exist() -> None:
    defs = load_schema(DEFINITION)["$defs"]
    titles = {d.get("title") for d in defs.values()}
    assert set(KINDS.values()) <= titles
    assert {
        "PolicyRule",
        "PolicyAppliesTo",
        "EnforcementMode",
        "PolicySeverity",
        "PolicyRuleKind",
    } <= titles


@pytest.mark.parametrize("kind", KINDS)
def test_each_kind_rejects_another_kinds_params(kind: str) -> None:
    doc = _definition()
    other = next(k for k in KINDS if k != kind)
    # Mutate a copy of the rule so its kind and params disagree.
    rule = _rule_for(doc, kind)
    rule["params"] = copy.deepcopy(_rule_for(_definition(), other)["params"])
    assert _errors(DEFINITION, doc), f"{kind} accepted params of {other}"


@pytest.mark.parametrize("kind", KINDS)
def test_each_kind_rejects_unknown_params_key(kind: str) -> None:
    doc = _definition()
    _rule_for(doc, kind)["params"]["expression"] = "x"
    assert _errors(DEFINITION, doc)


def test_unknown_rule_kind_rejected_by_enum() -> None:
    doc = _definition()
    doc["rules"][0]["kind"] = "identity_entitlement"
    assert _errors(DEFINITION, doc)


def test_33_rules_rejected_and_32_accepted() -> None:
    doc = _definition()
    template = _rule_for(doc, "required_owner")
    doc["rules"] = [{**copy.deepcopy(template), "rule_id": f"r{i}"} for i in range(32)]
    assert not _errors(DEFINITION, doc)
    doc["rules"].append({**copy.deepcopy(template), "rule_id": "r32"})
    assert _errors(DEFINITION, doc)


def test_empty_rules_rejected() -> None:
    doc = _definition()
    doc["rules"] = []
    assert _errors(DEFINITION, doc)


def test_published_needs_publish_evidence() -> None:
    doc = _definition()
    doc["published_audit_id"] = None
    assert _errors(DEFINITION, doc)
    doc["status"] = "draft"
    assert not _errors(DEFINITION, doc)


def test_mode_defaults_to_audit() -> None:
    defs = load_schema(DEFINITION)["$defs"]
    assert defs["enforcement_mode"]["default"] == "audit"
    assert load_schema(DEFINITION)["properties"]["mode"]["default"] == "audit"
    assert load_schema(BINDING)["properties"]["mode"]["default"] == "audit"


def test_open_ended_wording() -> None:
    defs = load_schema(DEFINITION)["$defs"]
    assert "open-ended: readers must tolerate unknown values" in defs["rule_kind"]["description"]
    entity = defs["required_approval_params"]["properties"]["entity_types"]
    assert "open-ended" in entity["description"].lower()
    point = load_schema(BINDING)["$defs"]["enforcement_point"]
    assert "open-ended: readers must tolerate unknown values" in point["description"]


def test_registration_entity_types_closed() -> None:
    doc = _definition()
    _rule_for(doc, "registration_required")["params"]["entity_types"] = ["person"]
    assert _errors(DEFINITION, doc)


def _long_free_strings(node: Any, path: str = "") -> Iterator[str]:
    """Yield the path of every string schema that could hold more than 128 free characters."""
    if isinstance(node, dict):
        if node.get("type") == "string" or (
            isinstance(node.get("type"), list) and "string" in node["type"]
        ):
            constrained = any(k in node for k in ("pattern", "enum", "const", "format"))
            limit = node.get("maxLength")
            if not constrained and (limit is None or limit > 128):
                yield path
        for key, value in node.items():
            yield from _long_free_strings(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _long_free_strings(value, f"{path}/{index}")


@pytest.mark.parametrize("rel", ALL_SCHEMAS)
def test_no_unbounded_free_text_string(rel: str) -> None:
    offenders = [p for p in _long_free_strings(load_schema(rel)) if "display_name" not in p]
    assert offenders == []


def test_free_text_walker_catches_an_unbounded_field() -> None:
    bad = {"type": "object", "properties": {"condition": {"type": "string"}}}
    assert list(_long_free_strings(bad)) == ["/properties/condition"]
    capped = {"properties": {"condition": {"type": "string", "maxLength": 4096}}}
    assert list(_long_free_strings(capped))
    fine = {"properties": {"note": {"type": "string", "maxLength": 64}}}
    assert not list(_long_free_strings(fine))


def test_no_expression_like_property_names() -> None:
    names = {
        name
        for rel in ALL_SCHEMAS
        for node in _walk(load_schema(rel))
        if isinstance(node.get("properties"), dict)
        for name in node["properties"]
    }
    assert not {
        n for n in names if n in {"expression", "condition", "query", "script", "code", "sql"}
    }
    assert "text" not in names
    assert not {n for n in names if is_body_field(n)}
    assert not names & FORBIDDEN_KEYS


@pytest.mark.parametrize("rel", ALL_SCHEMAS)
def test_every_object_is_closed(rel: str) -> None:
    for node in _walk(load_schema(rel)):
        if node.get("type") == "object" and "properties" in node:
            assert node.get("additionalProperties") is False
            assert not ({"key", "value"} <= set(node["properties"]))


def test_violation_evidence_and_ref_bounds() -> None:
    doc = _doc("policy-violation.open.json")
    assert not _errors(VIOLATION, doc)
    doc["evidence"][0]["ref"] = "x" * 513
    assert _errors(VIOLATION, doc)
    doc["evidence"] = []
    assert _errors(VIOLATION, doc)


# --------------------------------------------------------------- criterion 8: request/response


@pytest.mark.parametrize(
    "key", ["domain_id", "customer_id", "cloud", "tenant_id", "prompt", "content"]
)
def test_request_rejects_scope_and_content_keys(key: str) -> None:
    doc = _request()
    doc[key] = "x"
    assert _errors(REQUEST, doc)


def test_request_names_a_subject() -> None:
    doc = _request()
    assert check_decision_request_subject(doc) == []
    for name in ("agent_id", "model"):
        doc[name] = None
    assert check_decision_request_subject(doc)
    doc["data_asset_ids"] = ["commercial:acme:neurosphere:data_asset:orders"]
    assert check_decision_request_subject(doc) == []


def test_request_point_is_enforcement_point() -> None:
    doc = _request()
    doc["decision_point"] = "nowhere"
    assert _errors(REQUEST, doc)


@pytest.mark.parametrize("ttl", [-1, 3601])
def test_response_ttl_bounds(ttl: int) -> None:
    doc = _doc("policy-decision-response.audit.json")
    doc["cache_ttl_seconds"] = ttl
    assert _errors(RESPONSE, doc)
    for ok in (0, 3600):
        doc["cache_ttl_seconds"] = ok
        assert not _errors(RESPONSE, doc)


def test_response_list_caps() -> None:
    doc = _doc("policy-decision-response.audit.json")
    doc["matches"] = [copy.deepcopy(doc["matches"][0]) for _ in range(21)]
    assert _errors(RESPONSE, doc)
    doc = _doc("policy-decision-response.audit.json")
    doc["reason_codes"] = [f"code_{i}" for i in range(9)]
    assert _errors(RESPONSE, doc)


def test_exception_requires_expires_at() -> None:
    doc = _exception()
    del doc["expires_at"]
    assert _errors(EXCEPTION, doc)
    assert "expires_at" in load_schema(EXCEPTION)["required"]


def test_exception_window() -> None:
    doc = _exception()
    assert check_policy_exception_window(doc) == []
    doc["requested_at"] = "2026-01-01T00:00:00Z"
    doc["expires_at"] = "2027-01-01T00:00:00Z"
    assert check_policy_exception_window(doc) == []
    doc["expires_at"] = "2027-01-02T00:00:00Z"
    assert check_policy_exception_window(doc)
    doc["expires_at"] = "2026-01-01T00:00:00Z"
    assert check_policy_exception_window(doc)


def test_binding_target_null_or_target_ref() -> None:
    doc = _doc("enforcement-binding.gateway.json")
    assert doc["target"] is None
    doc["target"] = {
        "canonical_id": "commercial:acme:neurosphere:agent:support-bot",
        "entity_type": "agent",
    }
    assert not _errors(BINDING, doc)
    doc["target"] = {"canonical_id": "x"}
    assert _errors(BINDING, doc)
