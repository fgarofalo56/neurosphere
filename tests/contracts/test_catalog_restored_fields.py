"""PRP-70 item 1: tags, capabilities, environment, sensitivity and residency on catalog entities.

Every rule is checked against the JSON Schema (source of truth) and the generated Pydantic
model. Pydantic does not enforce ``uniqueItems`` (the generator drops it), so uniqueness is a
JSON Schema check only, as ``validate_mcp_tool_names_unique`` is for tool names (ADR-0004).
"""

from __future__ import annotations

import copy
from typing import Any

import pydantic
import pytest
import validators as v
from contract_support import SCHEMA_ROOT, load_json, model_for, schema_errors

AGENT = "catalog/v1/agent.schema.json"
TOOL = "catalog/v1/tool.schema.json"
AGENT_VERSION = "catalog/v1/agent_version.schema.json"
GROUNDING = "catalog/v1/grounding_source.schema.json"
QUERY = "query/v1/structured-query.schema.json"

CATALOG_EXAMPLES = SCHEMA_ROOT / "catalog" / "v1" / "examples" / "valid"
QUERY_EXAMPLES = SCHEMA_ROOT / "query" / "v1" / "examples" / "valid"


def _agent() -> dict[str, Any]:
    return load_json(CATALOG_EXAMPLES / "agent.tagged-capabilities-environment.json")


def _grounding() -> dict[str, Any]:
    return load_json(CATALOG_EXAMPLES / "grounding_source.sensitivity-residency.json")


def _accepted(rel: str, doc: dict[str, Any]) -> None:
    assert schema_errors(rel, doc) == []
    model_for(rel).model_validate(doc)


def _rejected_by_both(rel: str, doc: dict[str, Any]) -> None:
    assert schema_errors(rel, doc)
    with pytest.raises(pydantic.ValidationError):
        model_for(rel).model_validate(doc)


def test_valid_agent_with_tags_capabilities_environment() -> None:
    agent = _agent()
    assert agent["tags"] == ["invoice-processing"]
    assert agent["capabilities"] == ["document.summarize"]
    assert agent["environment"] == "production"
    _accepted(AGENT, agent)


@pytest.mark.parametrize("tag", ["Invoice", "has space", "-leading", "", "a" * 64])
def test_bad_tag_rejected(tag: str) -> None:
    agent = _agent()
    agent["tags"] = [tag]
    _rejected_by_both(AGENT, agent)


def test_tag_boundaries() -> None:
    agent = _agent()
    agent["tags"] = ["a" * 63, "0.x_y-z"]
    _accepted(AGENT, agent)


def test_more_than_32_tags_rejected() -> None:
    agent = _agent()
    agent["tags"] = [f"tag{i}" for i in range(33)]
    _rejected_by_both(AGENT, agent)
    agent["tags"] = [f"tag{i}" for i in range(32)]
    _accepted(AGENT, agent)


def test_duplicate_tags_rejected_by_json_schema() -> None:
    agent = _agent()
    agent["tags"] = ["dup", "dup"]
    assert schema_errors(AGENT, agent)


@pytest.mark.parametrize(
    "capability", ["a.b.c.d.e", "Doc.summarize", "document..summarize", "1doc", "doc.", "a" * 33]
)
def test_bad_capability_rejected(capability: str) -> None:
    agent = _agent()
    agent["capabilities"] = [capability]
    _rejected_by_both(AGENT, agent)


def test_capability_with_four_segments_accepted() -> None:
    agent = _agent()
    agent["capabilities"] = ["a.b.c.d", "single"]
    _accepted(AGENT, agent)


def test_more_than_64_capabilities_rejected() -> None:
    agent = _agent()
    agent["capabilities"] = [f"cap{i}" for i in range(65)]
    _rejected_by_both(AGENT, agent)


@pytest.mark.parametrize("environment", ["prod", "Production", ""])
def test_unknown_environment_rejected(environment: str) -> None:
    agent = _agent()
    agent["environment"] = environment
    _rejected_by_both(AGENT, agent)


def test_null_environment_rejected_by_json_schema() -> None:
    # The generated model types every defaulted field as nullable, so only JSON Schema rejects it.
    agent = _agent()
    agent["environment"] = None
    assert schema_errors(AGENT, agent)


@pytest.mark.parametrize(
    "environment", ["production", "staging", "development", "test", "sandbox", "unknown"]
)
def test_every_environment_accepted(environment: str) -> None:
    agent = _agent()
    agent["environment"] = environment
    _accepted(AGENT, agent)


def test_tool_with_capabilities_example() -> None:
    tool = load_json(CATALOG_EXAMPLES / "tool.capabilities.json")
    assert tool["capabilities"]
    _accepted(TOOL, tool)


def test_agent_version_semver() -> None:
    version = load_json(CATALOG_EXAMPLES / "agent_version.minimal-and-typical.json")
    for ok in ("1.2.3", "0.0.1-rc.1+build.5", "10.20.30"):
        _accepted(AGENT_VERSION, {**version, "semver": ok})
    _accepted(AGENT_VERSION, {**version, "semver": None})
    for bad in ("1.2", "01.2.3", "v1.2.3", "1.2.3.4", "x" * 129):
        _rejected_by_both(AGENT_VERSION, {**version, "semver": bad})
    _accepted(AGENT_VERSION, {**version, "tags": ["a"], "capabilities": ["doc.read"]})


def test_valid_grounding_source_with_sensitivity_and_geography() -> None:
    source = _grounding()
    assert source["sensitivity_categories"] == ["pii", "phi"]
    assert source["residency_geography"] == "eu_eea"
    _accepted(GROUNDING, source)


def test_duplicate_sensitivity_category_rejected_by_json_schema() -> None:
    source = _grounding()
    source["sensitivity_categories"] = ["pii", "pii"]
    assert schema_errors(GROUNDING, source)


def test_unknown_sensitivity_category_and_too_many_rejected() -> None:
    source = _grounding()
    source["sensitivity_categories"] = ["secret"]
    _rejected_by_both(GROUNDING, source)
    source["sensitivity_categories"] = ["pii"] * 11
    _rejected_by_both(GROUNDING, source)


@pytest.mark.parametrize("geography", ["europe", "EU_EEA", ""])
def test_unknown_geography_rejected(geography: str) -> None:
    source = _grounding()
    source["residency_geography"] = geography
    _rejected_by_both(GROUNDING, source)


def test_classification_is_unchanged() -> None:
    source = _grounding()
    for value in ("public", "internal", "confidential", "restricted", "unknown"):
        _accepted(GROUNDING, {**source, "classification": value})
    _rejected_by_both(GROUNDING, {**source, "classification": "pii"})


@pytest.mark.parametrize(
    ("rel", "example"),
    [
        (AGENT, "agent.minimal-and-typical.json"),
        (TOOL, "tool.minimal-and-typical.json"),
        (AGENT_VERSION, "agent_version.minimal-and-typical.json"),
        (GROUNDING, "grounding_source.minimal-and-typical.json"),
        ("catalog/v1/service.schema.json", "service.minimal-and-typical.json"),
        ("catalog/v1/model_deployment.schema.json", "model_deployment.minimal-and-typical.json"),
        ("catalog/v1/mcp_server.schema.json", "mcp_server.entra-streamable-http.json"),
    ],
)
def test_pre_change_document_validates_with_defaults(rel: str, example: str) -> None:
    doc = load_json(CATALOG_EXAMPLES / example)
    for field in (
        "tags",
        "capabilities",
        "environment",
        "semver",
        "sensitivity_categories",
        "residency_geography",
    ):
        assert field not in doc, f"{example} must predate the new fields"
    assert schema_errors(rel, doc) == []
    model = model_for(rel).model_validate(doc)
    dumped = model.model_dump(mode="json")
    properties = load_json(SCHEMA_ROOT / rel)["properties"]
    for field, default in (
        ("tags", []),
        ("capabilities", []),
        ("environment", "unknown"),
        ("semver", None),
        ("sensitivity_categories", []),
        ("residency_geography", None),
    ):
        if field in properties:
            assert dumped[field] == default, (rel, field)
        else:
            assert field not in dumped, (rel, field)


def test_new_fields_are_never_required() -> None:
    for rel, fields in (
        (AGENT, ("tags", "capabilities", "environment")),
        (TOOL, ("tags", "capabilities", "environment")),
        (AGENT_VERSION, ("tags", "capabilities", "semver")),
        (GROUNDING, ("tags", "environment", "sensitivity_categories", "residency_geography")),
    ):
        schema = load_json(SCHEMA_ROOT / rel)
        assert not set(fields) & set(schema["required"]), rel
        assert set(fields) <= set(schema["properties"]), rel


def test_open_ended_vocabularies_say_so() -> None:
    defs = load_json(SCHEMA_ROOT / "catalog/v1/common.schema.json")["$defs"]
    for name in ("capability", "sensitivity_category", "residency_geography"):
        assert "readers must tolerate unknown values" in defs[name]["description"], name


# ---- StructuredQuery -----------------------------------------------------------------------


def _grounding_query() -> dict[str, Any]:
    return load_json(QUERY_EXAMPLES / "structured-query.grounding-sensitivity.json")


def test_structured_query_accepts_new_fields() -> None:
    query = _grounding_query()
    _accepted(QUERY, query)
    assert v.check_structured_query_field_applicability(query) == []


@pytest.mark.parametrize(
    ("entity", "field", "op", "value"),
    [
        ("agent", "tag", "eq", "invoice-processing"),
        ("agent", "capability", "eq", "document.summarize"),
        ("tool", "capability", "ne", "crm.lookup"),
        ("service", "tag", "eq", "billing"),
        ("grounding_source", "sensitivity_category", "eq", "phi"),
        ("grounding_source", "residency_geography", "ne", "eu_eea"),
        ("grounding_source", "residency_region", "eq", "westeurope"),
        ("grounding_source", "contains_personal_data", "eq", True),
    ],
)
def test_filter_on_new_field_for_carrying_entity(
    entity: str, field: str, op: str, value: Any
) -> None:
    query = copy.deepcopy(_grounding_query())
    query["entity"] = entity
    query["filters"] = [{"field": field, "op": op, "value": value}]
    query["fields"] = ["id"]
    query["sort"] = [{"field": "updated_at", "direction": "desc"}]
    _accepted(QUERY, query)
    assert v.check_structured_query_field_applicability(query) == []


@pytest.mark.parametrize("entity", ["telemetry_event", "cost_record"])
def test_sensitivity_category_does_not_apply_outside_catalog(entity: str) -> None:
    query = copy.deepcopy(_grounding_query())
    query["entity"] = entity
    query["filters"] = [{"field": "sensitivity_category", "op": "eq", "value": "pii"}]
    query["fields"] = ["id"]
    query["sort"] = []
    # The field itself is on the schema allowlist; only the applicability validator rejects it.
    problems = v.check_structured_query_field_applicability(query)
    assert problems == [
        f"filters/0: field 'sensitivity_category' does not apply to entity {entity!r}"
    ]


@pytest.mark.parametrize(
    ("entity", "field"),
    [
        ("agent", "sensitivity_category"),
        ("agent", "residency_geography"),
        ("agent", "contains_personal_data"),
        ("service", "capability"),
        ("person", "residency_region"),
        ("person", "tag"),
    ],
)
def test_field_only_applies_to_entities_that_carry_it(entity: str, field: str) -> None:
    assert field not in v.FIELD_APPLICABILITY[entity]


def test_applicability_rows_for_carrying_entities() -> None:
    table = v.FIELD_APPLICABILITY
    for entity in ("agent", "agent_version", "tool", "service", "mcp_server", "model_deployment"):
        assert "tag" in table[entity], entity
    for entity in ("agent", "agent_version", "tool"):
        assert "capability" in table[entity], entity
    assert {
        "tag",
        "sensitivity_category",
        "residency_geography",
        "residency_region",
        "contains_personal_data",
    } <= table["grounding_source"]
