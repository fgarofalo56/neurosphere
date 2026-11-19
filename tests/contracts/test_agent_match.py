"""PRP-70 item 3: agent-match request, response and feedback contracts.

JSON Schema is the source of truth; the Pydantic assertions cover what the shape projection keeps
(extra="forbid", numeric bounds, patterns, defaults).
"""

from __future__ import annotations

import copy
from typing import Any

import pydantic
import pytest
from contract_support import SCHEMA_ROOT, load_json, load_schema, model_for, schema_errors

REC = SCHEMA_ROOT / "recommendations" / "v1" / "examples" / "valid"
REQUEST = "recommendations/v1/agent-match-request.schema.json"
RESPONSE = "recommendations/v1/agent-match-response.schema.json"
FB_REQUEST = "recommendations/v1/agent-match-feedback-request.schema.json"
FEEDBACK = "recommendations/v1/agent-match-feedback.schema.json"


def _doc(name: str) -> dict[str, Any]:
    return copy.deepcopy(load_json(REC / name))


def _request() -> dict[str, Any]:
    return _doc("agent-match-request.task-with-capabilities.json")


def _scored() -> dict[str, Any]:
    return _doc("agent-match-response.scored.json")


def _both_reject(rel: str, doc: dict[str, Any]) -> None:
    assert schema_errors(rel, doc), "JSON Schema must reject"
    with pytest.raises(pydantic.ValidationError):
        model_for(rel).model_validate(doc)


def test_valid_examples_pass_schema_and_model() -> None:
    cases = [
        (REQUEST, "agent-match-request.task-with-capabilities.json"),
        (RESPONSE, "agent-match-response.cold-start.json"),
        (RESPONSE, "agent-match-response.scored.json"),
        (FB_REQUEST, "agent-match-feedback-request.rejected.json"),
        (FEEDBACK, "agent-match-feedback.accepted.json"),
    ]
    for rel, name in cases:
        doc = _doc(name)
        assert schema_errors(rel, doc) == [], name
        model_for(rel).model_validate(doc)


@pytest.mark.parametrize("key", ["domain_id", "customer_id", "cloud", "unknown_key"])
def test_request_rejects_scope_and_unknown_keys(key: str) -> None:
    doc = _request()
    doc[key] = "commercial:contoso:catalog:domain:operations"
    _both_reject(REQUEST, doc)


def test_request_task_text_bounds() -> None:
    doc = _request()
    doc["task_text"] = "a" * 2000
    assert schema_errors(REQUEST, doc) == []
    doc["task_text"] = "a" * 2001
    _both_reject(REQUEST, doc)
    doc["task_text"] = "ab"
    _both_reject(REQUEST, doc)


def test_request_task_text_control_characters() -> None:
    doc = _request()
    doc["task_text"] = "line one\n\tline two"
    assert schema_errors(REQUEST, doc) == []
    model_for(REQUEST).model_validate(doc)
    for bad in ("beep \u0007 task", "nul \u0000 task", "del \u007f task", "esc \u001b task"):
        doc["task_text"] = bad
        _both_reject(REQUEST, doc)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("limit", 51),
        ("limit", 0),
        ("max_graph_depth", 4),
        ("max_graph_depth", -1),
        ("required_capabilities", [f"cap.n{i}" for i in range(17)]),
        ("preferred_tags", [f"tag{i}" for i in range(17)]),
        (
            "context_entity_ids",
            [f"commercial:contoso:foundry:agent:a{i}" for i in range(21)],
        ),
        ("candidate_types", ["model"]),
        ("environment", "prod"),
    ],
)
def test_request_bounds(field: str, value: Any) -> None:
    doc = _request()
    doc[field] = value
    _both_reject(REQUEST, doc)


def test_request_defaults() -> None:
    doc = {"schema_version": "1.0.0", "task_text": "find a summarizer"}
    assert schema_errors(REQUEST, doc) == []
    props = load_schema(REQUEST)["properties"]
    assert props["limit"]["default"] == 10
    assert props["max_graph_depth"]["default"] == 2
    assert props["candidate_types"]["default"] == ["agent"]
    assert props["environment"]["default"] is None
    model = model_for(REQUEST).model_validate(doc)
    assert model.limit == 10
    assert model.max_graph_depth == 2
    assert model.candidate_types == ["agent"]
    assert model.environment is None


def test_response_requires_signals_on_every_candidate() -> None:
    doc = _scored()
    del doc["candidates"][1]["signals"]
    _both_reject(RESPONSE, doc)


def test_signal_value_null_is_unknown_and_accepted() -> None:
    doc = _doc("agent-match-response.cold-start.json")
    assert doc["cold_start"] is True
    assert "historical_success" in doc["signals_unavailable"]
    signal = doc["candidates"][0]["signals"][1]
    assert signal["signal"] == "historical_success"
    assert signal["value"] is None
    assert schema_errors(RESPONSE, doc) == []
    model_for(RESPONSE).model_validate(doc)
    schema = load_schema(RESPONSE)
    assert "null means unknown" in schema["$defs"]["signal"]["properties"]["value"]["description"]
    assert "not a probability" in schema["$defs"]["candidate"]["properties"]["score"]["description"]


@pytest.mark.parametrize("value", [1.2, -0.1])
def test_signal_value_out_of_range_rejected(value: float) -> None:
    doc = _scored()
    doc["candidates"][0]["signals"][0]["value"] = value
    _both_reject(RESPONSE, doc)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("score",), 1.5),
        (("score",), -0.2),
        (("signals", 0, "weight"), 1.1),
        (("signals", 0, "contribution"), -1.5),
        (("signals", 0, "signal"), "vibes"),
        (("relations",), [{"relation_type": "uses_model", "entity_id": "x", "direction": "out"}]),
    ],
)
def test_candidate_bounds(path: tuple[Any, ...], value: Any) -> None:
    doc = _scored()
    target = doc["candidates"][0]
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    _both_reject(RESPONSE, doc)


def test_response_collection_caps_and_partial_reason() -> None:
    doc = _scored()
    base = doc["candidates"][0]
    doc["candidates"] = [copy.deepcopy(base) for _ in range(51)]
    _both_reject(RESPONSE, doc)

    doc = _scored()
    rel = {
        "relation_type": "uses_model",
        "entity_id": "commercial:contoso:foundry:model_deployment:gpt-synthetic",
        "direction": "outgoing",
    }
    doc["candidates"][0]["relations"] = [
        {**rel, "entity_id": f"{rel['entity_id']}-{i}"} for i in range(21)
    ]
    _both_reject(RESPONSE, doc)

    doc = _scored()
    for ok in ("limit", "timeout_ms", None):
        doc["partial_reason"] = ok
        assert schema_errors(RESPONSE, doc) == []
    doc["partial_reason"] = "other"
    _both_reject(RESPONSE, doc)


def test_response_generated_titles() -> None:
    defs = load_schema(RESPONSE)["$defs"]
    assert defs["candidate"]["title"] == "AgentMatchCandidate"
    assert defs["signal"]["title"] == "AgentMatchSignal"


def _string_leaves(node: Any, path: str = "") -> list[tuple[str, dict[str, Any]]]:
    """Every sub-schema that describes a string, with its property path."""
    out: list[tuple[str, dict[str, Any]]] = []
    if isinstance(node, dict):
        if node.get("type") == "string":
            out.append((path, node))
        for key, child in node.items():
            out += _string_leaves(child, f"{path}/{key}")
    elif isinstance(node, list):
        for i, child in enumerate(node):
            out += _string_leaves(child, f"{path}/{i}")
    return out


def _resolve(node: dict[str, Any]) -> dict[str, Any]:
    """Follow a relative $ref into the catalog common library."""
    ref = node.get("$ref")
    if not ref:
        return node
    file, _, pointer = ref.partition("#")
    assert file.endswith("common.schema.json"), ref
    target: Any = load_json(SCHEMA_ROOT / "catalog" / "v1" / "common.schema.json")
    for part in pointer.lstrip("/").split("/"):
        target = target[part]
    return target


def _free_text_properties(schema: dict[str, Any]) -> list[str]:
    """String properties that are neither enum, nor pattern-constrained, nor date-time."""
    bad: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            props = node.get("properties")
            if isinstance(props, dict):
                for name, sub in props.items():
                    check(sub, f"{path}/{name}")
                    walk(sub, f"{path}/{name}")
            for key, child in node.items():
                if key != "properties":
                    walk(child, f"{path}/{key}")
        elif isinstance(node, list):
            for i, child in enumerate(node):
                walk(child, f"{path}/{i}")

    def check(sub: dict[str, Any], path: str) -> None:
        for alt in sub.get("oneOf", [sub]):
            leaf = _resolve(alt)
            items = leaf.get("items")
            if leaf.get("type") == "array" and items is not None:
                leaf = _resolve(items)
            if leaf.get("type") != "string":
                continue
            if "enum" in leaf or "pattern" in leaf or leaf.get("format") == "date-time":
                continue
            bad.append(path)

    walk(schema, "")
    return bad


@pytest.mark.parametrize("rel", [FB_REQUEST, FEEDBACK])
def test_feedback_schemas_have_no_free_text_property(rel: str) -> None:
    assert _free_text_properties(load_schema(rel)) == []
    schema = load_schema(rel)
    assert schema["additionalProperties"] is False
    assert not {"comment", "reason", "notes", "text", "task_text"} & set(schema["properties"])
    # sanity: the walker does see the string properties it is meant to police
    assert _string_leaves(schema)


def test_walker_catches_a_free_text_property() -> None:
    """The walker is not vacuous: a free-text sibling would be reported."""
    schema = copy.deepcopy(load_schema(FB_REQUEST))  # load_schema is cached: never mutate it
    schema["properties"]["comment"] = {"type": "string", "maxLength": 500}
    assert _free_text_properties(schema) == ["/comment"]


def test_feedback_request_rejects_comment_and_bad_codes() -> None:
    doc = _doc("agent-match-feedback-request.rejected.json")
    doc["comment"] = "not what I wanted"
    _both_reject(FB_REQUEST, doc)
    doc = _doc("agent-match-feedback-request.rejected.json")
    doc["reason_code"] = "because"
    _both_reject(FB_REQUEST, doc)
    doc["reason_code"] = None
    assert schema_errors(FB_REQUEST, doc) == []


def test_stored_feedback_has_digest_not_task_text() -> None:
    schema = load_schema(FEEDBACK)
    assert "task_digest" in schema["properties"]
    assert "task_text" not in schema["properties"]
    assert "task_digest" in schema["required"]
    doc = _doc("agent-match-feedback.accepted.json")
    doc["task_text"] = "summarize the contracts"
    _both_reject(FEEDBACK, doc)
    for bad in ("sha256:abc", "SHA256:" + "a" * 64, "sha256:" + "A" * 64, "a" * 64):
        doc = _doc("agent-match-feedback.accepted.json")
        doc["task_digest"] = bad
        _both_reject(FEEDBACK, doc)
