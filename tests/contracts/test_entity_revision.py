"""PRP-70 item 2: EntityRevision and EntityRevisionDiff.

The body pin by ``entity_type`` is an ``if/then`` rule, which JSON Schema enforces and the
generated Pydantic model cannot (ADR-0004 shape projection). The Pydantic projection of
``body`` is therefore a plain union of the 14 entity models: a body of another entity type is
still accepted by Pydantic, and core must validate it again against the entity's own model
(PRP-76). The tests below assert the JSON Schema behaviour and document the projection by
construction rather than asserting it.
"""

from __future__ import annotations

import copy
from typing import Any

import pydantic
import pytest
import validators as v
from contract_support import SCHEMA_ROOT, load_json, model_for, schema_errors, sha256_jcs

REVISION = "catalog/v1/entity_revision.schema.json"
DIFF = "catalog/v1/entity_revision_diff.schema.json"
COMMON = SCHEMA_ROOT / "catalog" / "v1" / "common.schema.json"
EXAMPLES = SCHEMA_ROOT / "catalog" / "v1" / "examples"

# entity_type -> schema file that its revision body must satisfy.
ENTITY_SCHEMAS = {
    "person": "person",
    "agent": "agent",
    "agent_version": "agent_version",
    "model_deployment": "model_deployment",
    "grounding_source": "grounding_source",
    "tool": "tool",
    "service": "service",
    "domain": "domain",
    "owner": "owner",
    "policy": "policy",
    "recommendation": "recommendation_reference",
    "run_reference": "run_reference",
    "grant": "grant",
    "mcp_server": "mcp_server",
}


def _revision() -> dict[str, Any]:
    return load_json(EXAMPLES / "valid" / "entity_revision.agent-update.json")


def _diff() -> dict[str, Any]:
    return load_json(EXAMPLES / "valid" / "entity_revision_diff.agent-capabilities.json")


def test_fourteen_entity_types_map_to_body_schemas() -> None:
    enum = load_json(COMMON)["$defs"]["entity_type"]["enum"]
    assert sorted(enum) == sorted(ENTITY_SCHEMAS)
    schema = load_json(SCHEMA_ROOT / REVISION)
    refs = sorted(m["$ref"] for m in schema["properties"]["body"]["anyOf"])
    assert refs == sorted(f"{name}.schema.json" for name in ENTITY_SCHEMAS.values())
    pinned = [m["then"]["properties"]["body"]["$ref"] for m in schema["allOf"]]
    assert sorted(pinned) == refs


def test_examples_accepted_by_schema_and_model() -> None:
    for name in ("entity_revision.agent-update", "entity_revision.grounding-source-create"):
        doc = load_json(EXAMPLES / "valid" / f"{name}.json")
        assert schema_errors(REVISION, doc) == []
        model_for(REVISION).model_validate(doc)
    assert schema_errors(DIFF, _diff()) == []
    model_for(DIFF).model_validate(_diff())


def _tool_under_agent() -> dict[str, Any]:
    """An agent revision carrying a tool body. Kept inline, not as an invalid example file:
    the catalog example suite requires one top-level error per invalid file, and an if/then
    pin failure reports several (one per violated member of the pinned schema)."""
    doc = _revision()
    doc["body"] = load_json(EXAMPLES / "valid" / "tool.capabilities.json")
    doc["body_sha256"] = sha256_jcs(doc["body"])
    return doc


def test_body_of_another_entity_type_rejected_by_json_schema() -> None:
    doc = _tool_under_agent()
    assert doc["entity_type"] == "agent" and doc["body"]["entity_type"] == "tool"
    assert schema_errors(REVISION, doc)
    # The same body is accepted once the revision names the matching type.
    doc["entity_type"] = "tool"
    doc["entity_id"] = doc["body"]["id"]
    doc["revision_id"] = f"{doc['entity_id']}@{doc['body']['version']}"
    assert schema_errors(REVISION, doc) == []


def test_pydantic_projection_does_not_enforce_the_body_pin() -> None:
    """Documented projection: the union body admits a tool under entity_type agent."""
    model_for(REVISION).model_validate(_tool_under_agent())


@pytest.mark.parametrize("entity_type", sorted(set(ENTITY_SCHEMAS) - {"agent"}))
def test_every_type_pin_rejects_the_agent_body(entity_type: str) -> None:
    doc = _revision()
    doc["entity_type"] = entity_type
    assert schema_errors(REVISION, doc)


def test_missing_body_sha256_rejected_by_both() -> None:
    doc = _revision()
    del doc["body_sha256"]
    assert schema_errors(REVISION, doc)
    with pytest.raises(pydantic.ValidationError):
        model_for(REVISION).model_validate(doc)


@pytest.mark.parametrize("digest", ["sha256:" + "A" * 64, "sha256:abc", "md5:" + "a" * 64])
def test_bad_digest_rejected(digest: str) -> None:
    doc = _revision()
    doc["body_sha256"] = digest
    assert schema_errors(REVISION, doc)


@pytest.mark.parametrize(
    "revision_id",
    [
        "commercial:contoso:foundry:agent:invoice-summarizer@3",
        "government:contoso:foundry:agent:invoice-summarizer@12",
    ],
)
def test_revision_id_shape_accepted(revision_id: str) -> None:
    doc = _revision()
    doc["revision_id"] = revision_id
    # cloud pin is not part of revision_id; only the shape is checked here.
    errors = [e for e in schema_errors(REVISION, doc) if "revision_id" in str(e)]
    assert errors == []


@pytest.mark.parametrize(
    "revision_id",
    [
        "commercial:contoso:foundry:agent:invoice-summarizer",
        "commercial:contoso:foundry:agent:invoice-summarizer@0",
        "commercial:contoso:foundry:agent:invoice-summarizer@03",
        "commercial:contoso:foundry:agent:invoice-summarizer@x",
        "invoice-summarizer@3",
    ],
)
def test_revision_id_shape_rejected(revision_id: str) -> None:
    doc = _revision()
    doc["revision_id"] = revision_id
    assert schema_errors(REVISION, doc)
    with pytest.raises(pydantic.ValidationError):
        model_for(REVISION).model_validate(doc)


def test_nullable_members_are_optional() -> None:
    doc = _revision()
    for key in ("previous_version", "recorded_by", "change_reason", "audit_id", "correlation_id"):
        del doc[key]
    assert schema_errors(REVISION, doc) == []
    model = model_for(REVISION).model_validate(doc)
    assert model.previous_version is None


@pytest.mark.parametrize("operation", ["create", "update", "deprecate", "recertify", "retire"])
def test_operations(operation: str) -> None:
    doc = _revision()
    doc["operation"] = operation
    assert schema_errors(REVISION, doc) == []
    doc["operation"] = "delete"
    assert schema_errors(REVISION, doc)


def test_changed_fields_and_reason_limits() -> None:
    doc = _revision()
    doc["changed_fields"] = [f"field_{i}" for i in range(65)]
    assert schema_errors(REVISION, doc)
    doc = _revision()
    doc["change_reason"] = "x" * 501
    assert schema_errors(REVISION, doc)
    doc["change_reason"] = ""
    assert schema_errors(REVISION, doc)


def _many_changes(count: int) -> list[dict[str, Any]]:
    return [
        {"path": f"/field_{i}", "op": "added", "before": None, "after": i} for i in range(count)
    ]


def test_201_changes_rejected_by_json_schema_and_pydantic() -> None:
    doc = _diff()
    doc["changes"] = _many_changes(200)
    assert schema_errors(DIFF, doc) == []
    model_for(DIFF).model_validate(doc)
    doc["changes"] = _many_changes(201)
    assert schema_errors(DIFF, doc)
    with pytest.raises(pydantic.ValidationError):
        model_for(DIFF).model_validate(doc)


@pytest.mark.parametrize("path", ["tags", "/Tags", "/a/b/c/d/e/f/g", "", "/a b"])
def test_bad_change_path_rejected(path: str) -> None:
    doc = _diff()
    doc["changes"] = [{"path": path, "op": "changed", "before": 1, "after": 2}]
    assert schema_errors(DIFF, doc)


def test_diff_unknown_op_and_extra_key_rejected() -> None:
    doc = _diff()
    doc["changes"][0]["op"] = "moved"
    assert schema_errors(DIFF, doc)
    doc = _diff()
    doc["extra"] = 1
    assert schema_errors(DIFF, doc)


def test_version_order_validator_on_revisions() -> None:
    doc = _revision()
    assert v.check_revision_version_order(doc) == []
    doc["previous_version"] = None
    assert v.check_revision_version_order(doc) == []
    doc["previous_version"] = doc["entity_version"]
    assert v.check_revision_version_order(doc)
    doc["previous_version"] = doc["entity_version"] + 1
    assert v.check_revision_version_order(doc)


def test_version_order_validator_on_diffs() -> None:
    doc = _diff()
    assert v.check_revision_version_order(doc) == []
    doc["from_version"] = doc["to_version"]
    assert v.check_revision_version_order(copy.deepcopy(doc))
    doc["from_version"] = doc["to_version"] + 1
    assert v.check_revision_version_order(doc)


def test_validator_is_registered_for_both_schemas() -> None:
    table = v.single_document_validators({"confirmation_hash": {}})
    assert v.check_revision_version_order in table[REVISION]
    assert v.check_revision_version_order in table[DIFF]
