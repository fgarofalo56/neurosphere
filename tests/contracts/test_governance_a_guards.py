"""Cross-cutting guard and secrecy suite for the governance contracts (PRP-99 item 6).

Per-schema cases live in the other ``test_governance_a_*`` files. This file walks whole trees:
property names against the shared body guard and the audit content guard, key+value shapes,
content containment, nobody embedding the two content schemas, credential-like names, and the
closed telemetry event. Every walker has a self-test that plants a violation in a deepcopy of a
schema (``load_schema`` is cached) and asserts the walker catches it.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from contract_support import (
    iter_subschemas,
    load_schema,
    reachable_from,
    ref_target,
    resolve_pointer,
    schema_files,
)
from neurosphere_core.audit.content_guard import FORBIDDEN_KEYS
from neurosphere_core.payload import is_body_field
from test_admin_no_credential_values import credential_findings

ENVELOPE = "telemetry/v1/content-envelope.schema.json"
REDACTED = "interactions/v1/redacted-content.schema.json"
CONTENT_SCHEMAS = frozenset({ENVELOPE, REDACTED})
EVENT = "telemetry/v1/telemetry-event.schema.json"
SYSTEM_SETTING = "admin/v1/system-setting.schema.json"
DEDUP_PATTERN = "^sha256:[a-f0-9]{64}$"

# Areas that hold the governance contracts. `admin/v1` is covered through its three new
# `system_setting` members, and through the notification, policy and interaction bodies that the
# three new `admin_kind` pins reference (those live in `notifications/v1` and `policy/v1`).
GUARD_PREFIXES = (
    "telemetry/v1/",
    "interactions/v1/",
    "policy/v1/",
    "notifications/v1/",
    "audit/v1/",
)
GUARDED = tuple(
    rel for rel in schema_files() if rel.startswith(GUARD_PREFIXES) or rel == SYSTEM_SETTING
)
CREDENTIAL_AREAS = tuple(
    rel
    for rel in schema_files()
    if rel.startswith(("interactions/v1/", "policy/v1/", "notifications/v1/"))
)
# Areas added or extended by PRP-99, held to the "no unbounded string" rule.
BOUNDED_STRING_AREAS = tuple(
    rel
    for rel in schema_files()
    if rel.startswith(("interactions/v1/", "policy/v1/", "notifications/v1/", "telemetry/v1/"))
    or rel == SYSTEM_SETTING
)

# Schemas that must carry no `text` property at any depth, own file or referenced.
NO_TEXT_SCHEMAS = (
    "interactions/v1/interaction-record.schema.json",
    "policy/v1/policy-violation.schema.json",
    "notifications/v1/notification.schema.json",
    "interactions/v1/interaction-export-manifest.schema.json",
    "audit/v1/audit-record.schema.json",
    EVENT,
    SYSTEM_SETTING,
)

# Strings longer than 1024 characters and `text` properties that predate PRP-99 and sit outside
# the governance areas. Pinned by exact pointer: a new one anywhere fails the containment test.
GRANDFATHERED_LONG: frozenset[tuple[str, str]] = frozenset(
    {
        ("actions/v1/approval-decision.schema.json", "/properties/reason"),
        ("admin/v1/price-sheet-upload.schema.json", "/properties/notes"),
        ("catalog/v1/agent.schema.json", "/properties/description/anyOf/0"),
        ("catalog/v1/common.schema.json", "/$defs/lock/properties/reason/anyOf/0"),
        ("catalog/v1/common.schema.json", "/$defs/curation/properties/reason"),
        ("catalog/v1/edge_override.schema.json", "/properties/reason"),
        ("catalog/v1/mcp_server.schema.json", "/properties/url"),
        (
            "catalog/v1/mcp_server.schema.json",
            "/properties/tools/items/properties/description/anyOf/0",
        ),
        ("deployment/v1/capability-matrix-entry.schema.json", "/properties/source_url"),
        ("deployment/v1/capability-matrix-entry.schema.json", "/properties/notes"),
        ("errors/v1/problem-details.schema.json", "/properties/type"),
        ("errors/v1/problem-details.schema.json", "/properties/detail"),
        ("errors/v1/problem-details.schema.json", "/properties/instance"),
        ("recommendations/v1/agent-match-request.schema.json", "/properties/task_text"),
    }
)
GRANDFATHERED_TEXT: frozenset[tuple[str, str]] = frozenset(
    {("chart/v1/chart-plan.schema.json", "/$defs/encoding")}
)

# telemetry-event top-level properties as of the PRP-99 contract (none added by PRP-99).
TELEMETRY_TOP_LEVEL = (
    "schema_version",
    "event_id",
    "event_time",
    "ingestion_time",
    "cloud",
    "customer_id",
    "domain_id",
    "source_id",
    "external_agent_id",
    "canonical_agent_id",
    "request_id",
    "trace_id",
    "span_id",
    "parent_span_id",
    "span_kind",
    "retry_attempt",
    "provider",
    "model",
    "model_version",
    "environment",
    "outcome",
    "duration_ms",
    "token_breakdown",
    "data_source_refs",
    "classification",
    "sampling",
    "payload_ref",
    "tool",
    "service",
    "mcp_server_ref",
)
PAYLOAD_REF_PRE_PRP = ("pointer", "classification", "redaction_state")
PAYLOAD_REF_ADDED = (
    "interaction_id",
    "capture_policy_id",
    "capture_policy_version",
    "detector_set_version",
    "detected_categories",
    "content_parts",
)


# ------------------------------------------------------------------------------ walkers


def _declared_names(schema: dict[str, Any]) -> Iterator[tuple[str, str]]:
    """``(pointer, name)`` for every declared property, pattern, required or dependent name."""
    for sub in iter_subschemas(schema):
        for keyword in ("properties", "patternProperties", "dependentSchemas"):
            members = sub.node.get(keyword)
            if isinstance(members, dict):
                for name in members:
                    yield f"{sub.pointer}/{keyword}/{name}", name
        for keyword in ("required",):
            members = sub.node.get(keyword)
            if isinstance(members, list):
                for name in members:
                    if isinstance(name, str):
                        yield f"{sub.pointer}/{keyword}/{name}", name
        dependent = sub.node.get("dependentRequired")
        if isinstance(dependent, dict):
            for name in dependent:
                yield f"{sub.pointer}/dependentRequired/{name}", name


def _literal(name: str) -> str:
    """Strip regex anchors so a `patternProperties` key is judged by its literal text."""
    return name.removeprefix("^").removesuffix("$")


def guard_name_findings(schema: dict[str, Any]) -> list[str]:
    """Names that the ingest body guard or the audit content guard would drop or reject."""
    return [
        f"{pointer} ({name})"
        for pointer, name in _declared_names(schema)
        if is_body_field(_literal(name)) or _literal(name).lower() in FORBIDDEN_KEYS
    ]


def key_value_findings(schema: dict[str, Any]) -> list[str]:
    """Object schemas declaring both `key` and `value` (the OTLP attribute shape)."""
    return [
        sub.pointer or "/"
        for sub in iter_subschemas(schema)
        if isinstance(sub.node.get("properties"), dict)
        and {"key", "value"} <= set(sub.node["properties"])
    ]


def _is_string_node(node: dict[str, Any]) -> bool:
    kind = node.get("type")
    return kind == "string" or (isinstance(kind, list) and "string" in kind)


def long_string_findings(schema: dict[str, Any]) -> list[str]:
    """Pointers of subschemas whose `maxLength` exceeds 1024."""
    return [
        sub.pointer
        for sub in iter_subschemas(schema)
        if isinstance(sub.node.get("maxLength"), int) and sub.node["maxLength"] > 1024
    ]


def text_property_findings(schema: dict[str, Any]) -> list[str]:
    """Pointers of subschemas declaring a `text` property."""
    return [
        sub.pointer
        for sub in iter_subschemas(schema)
        if isinstance(sub.node.get("properties"), dict) and "text" in sub.node["properties"]
    ]


_BOUNDING_KEYWORDS = ("maxLength", "pattern", "enum", "const", "format")


def unbounded_string_findings(schema: dict[str, Any]) -> list[str]:
    """String schemas with no bounding keyword.

    Subschemas under `if`/`then`/`else`/`not`/`contains` are refinement overlays of a property
    declared (and bounded) elsewhere, so they are not judged on their own.
    """
    return [
        sub.pointer
        for sub in iter_subschemas(schema)
        if _is_string_node(sub.node)
        and not sub.under_conditional
        and not any(key in sub.node for key in _BOUNDING_KEYWORDS)
    ]


def content_refs(rel: str, schema: dict[str, Any]) -> list[str]:
    """Every `$ref` in `schema` (a copy of file `rel`) that targets a content schema."""
    found = []
    for sub in iter_subschemas(schema):
        ref = sub.node.get("$ref")
        if not isinstance(ref, str):
            continue
        target, _ = _target_of(rel, schema, ref)
        names_content = any(
            name in ref for name in ("content-envelope.schema.json", "redacted-content.schema.json")
        )
        # A local `#/$defs/...` ref inside a content schema targets that schema itself: not an
        # embedding by another schema.
        if (target in CONTENT_SCHEMAS or names_content) and target != rel:
            found.append(f"{sub.pointer}: {ref}")
    return found


def _target_of(rel: str, schema: dict[str, Any], ref: str) -> tuple[str | None, str]:
    if ref.startswith("#"):
        return rel, ref[1:]
    from urllib.parse import urldefrag, urljoin

    from contract_support import rel_from_uri

    base, fragment = urldefrag(urljoin(schema["$id"], ref))
    return rel_from_uri(base), fragment


def open_object_findings(schema: dict[str, Any]) -> list[str]:
    """Object schemas (outside conditional overlays) lacking `additionalProperties: false`."""
    return [
        sub.pointer or "/"
        for sub in iter_subschemas(schema)
        if (sub.node.get("type") == "object" or "properties" in sub.node)
        and not sub.under_conditional
        and sub.node.get("additionalProperties") is not False
    ]


def _resolve_property(schema: dict[str, Any], pointer: str) -> dict[str, Any]:
    """Resolve the schema at `pointer`, following one local `#/$defs/...` `$ref`."""
    body = resolve_pointer(schema, pointer)
    ref = body.get("$ref") if isinstance(body, dict) else None
    if isinstance(ref, str) and ref.startswith("#/"):
        return resolve_pointer(schema, ref[1:])
    return body


def governance_credential_findings(rel: str, schema: dict[str, Any] | None = None) -> list[str]:
    """PRP-37 walker findings, minus `dedup_key` while it is pinned to a sha256 digest.

    Clarification 19: `dedup_key` is a digest, never a key. The exemption is shape-bound.
    """
    document = schema if schema is not None else load_schema(rel)
    remaining = []
    for finding in credential_findings(rel, document):
        pointer = finding.removeprefix(rel)
        name = pointer.rsplit("/", 1)[-1]
        if name == "dedup_key" and pointer.endswith("/properties/dedup_key"):
            body = _resolve_property(document, pointer)
            if body.get("pattern") == DEDUP_PATTERN:
                continue
        remaining.append(finding)
    return remaining


def _plant(rel: str, edit: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    doc = copy.deepcopy(load_schema(rel))
    edit(doc)
    return doc


# ------------------------------------------------------------------ 1. guard names


@pytest.mark.parametrize("rel", GUARDED)
def test_no_property_name_trips_the_body_or_content_guard(rel: str) -> None:
    # `text` and `parts` (the content channel) are not body-guard names, so no schema needs an
    # exemption here: ContentEnvelope and RedactedContent are walked like everything else.
    assert guard_name_findings(load_schema(rel)) == []


@pytest.mark.parametrize(
    "name",
    ["prompt", "Response", "gen_ai.prompt", "app.response", "messages", "completion", "body"],
)
def test_guard_name_walker_catches_planted_names(name: str) -> None:
    def edit(doc: dict[str, Any]) -> None:
        doc.setdefault("$defs", {})["planted"] = {
            "type": "object",
            "properties": {name: {"type": "string"}},
        }

    assert guard_name_findings(_plant(EVENT, edit))


def test_guard_name_walker_catches_names_in_branches() -> None:
    def edit(doc: dict[str, Any]) -> None:
        doc["allOf"] = [
            {"if": {"required": ["x"]}, "then": {"properties": {"prompt": {"type": "string"}}}},
            {"anyOf": [{"patternProperties": {"^response$": {"type": "string"}}}]},
        ]

    assert len(guard_name_findings(_plant(EVENT, edit))) >= 2


def test_guarded_set_covers_the_governance_areas() -> None:
    for expected in (
        EVENT,
        ENVELOPE,
        REDACTED,
        "interactions/v1/interaction-record.schema.json",
        "policy/v1/policy-definition.schema.json",
        "notifications/v1/notification-channel.schema.json",
        "audit/v1/audit-record.schema.json",
        SYSTEM_SETTING,
    ):
        assert expected in GUARDED


def test_system_setting_members_are_walked() -> None:
    names = {name for _, name in _declared_names(load_schema(SYSTEM_SETTING))}
    assert {"kek_uri", "egress_allowed_hosts", "sdk_failure_mode"} <= names


# ------------------------------------------------------------------ 2. key + value


@pytest.mark.parametrize("rel", GUARDED)
def test_no_object_declares_both_key_and_value(rel: str) -> None:
    assert key_value_findings(load_schema(rel)) == []


def test_key_value_walker_catches_a_planted_attribute_shape() -> None:
    def edit(doc: dict[str, Any]) -> None:
        doc["$defs"]["planted"] = {
            "type": "object",
            "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
        }

    assert key_value_findings(_plant(EVENT, edit)) == ["/$defs/planted"]


# ------------------------------------------------------------------ 3. content containment


def test_only_the_two_content_schemas_declare_text_or_long_strings() -> None:
    text_owners: set[str] = set()
    long_owners: set[str] = set()
    stray_text: list[tuple[str, str]] = []
    stray_long: list[tuple[str, str]] = []
    for rel in schema_files():
        schema = load_schema(rel)
        for pointer in text_property_findings(schema):
            text_owners.add(rel)
            if rel not in CONTENT_SCHEMAS and (rel, pointer) not in GRANDFATHERED_TEXT:
                stray_text.append((rel, pointer))
        for pointer in long_string_findings(schema):
            long_owners.add(rel)
            if rel not in CONTENT_SCHEMAS and (rel, pointer) not in GRANDFATHERED_LONG:
                stray_long.append((rel, pointer))
    assert stray_text == []
    assert stray_long == []
    # Both content schemas really are the carriers (the rule is not vacuous).
    assert CONTENT_SCHEMAS <= text_owners
    assert CONTENT_SCHEMAS <= long_owners


def test_grandfathered_entries_still_exist() -> None:
    """A stale entry would silently allow a future field at the same pointer."""
    present_long = {
        (rel, pointer)
        for rel in schema_files()
        for pointer in long_string_findings(load_schema(rel))
    }
    present_text = {
        (rel, pointer)
        for rel in schema_files()
        for pointer in text_property_findings(load_schema(rel))
    }
    assert GRANDFATHERED_LONG <= present_long
    assert GRANDFATHERED_TEXT <= present_text


def test_no_governance_area_outside_the_content_schemas_is_grandfathered() -> None:
    for rel, _ in GRANDFATHERED_LONG | GRANDFATHERED_TEXT:
        assert not rel.startswith(GUARD_PREFIXES)
        assert rel != SYSTEM_SETTING


def test_containment_walkers_catch_planted_content() -> None:
    def add_text(doc: dict[str, Any]) -> None:
        doc["properties"]["text"] = {"type": "string"}

    def add_long(doc: dict[str, Any]) -> None:
        doc["properties"]["note"] = {"type": "string", "maxLength": 1025}

    record = "interactions/v1/interaction-record.schema.json"
    assert text_property_findings(_plant(record, add_text)) == [""]
    assert long_string_findings(_plant(record, add_long)) == ["/properties/note"]
    assert long_string_findings(load_schema(record)) == []


@pytest.mark.parametrize("rel", BOUNDED_STRING_AREAS)
def test_no_governance_string_is_unbounded(rel: str) -> None:
    assert unbounded_string_findings(load_schema(rel)) == []


def test_unbounded_string_walker_catches_a_planted_string() -> None:
    def edit(doc: dict[str, Any]) -> None:
        doc["properties"]["loose"] = {"type": "string"}

    record = "interactions/v1/interaction-record.schema.json"
    assert unbounded_string_findings(_plant(record, edit)) == ["/properties/loose"]


# ------------------------------------------------------------------ 4. nobody embeds content


@pytest.mark.parametrize("rel", schema_files())
def test_no_schema_references_a_content_schema(rel: str) -> None:
    assert content_refs(rel, load_schema(rel)) == []


@pytest.mark.parametrize(
    "ref",
    [
        "../../telemetry/v1/content-envelope.schema.json",
        "../../interactions/v1/redacted-content.schema.json#/$defs/secret_free_text",
        "https://neurosphere.invalid/schemas/telemetry/v1/content-envelope.schema.json",
        "redacted-content.schema.json",
    ],
)
def test_content_ref_walker_catches_planted_refs(ref: str) -> None:
    def edit(doc: dict[str, Any]) -> None:
        doc["properties"]["embedded"] = {"$ref": ref}

    record = "interactions/v1/interaction-record.schema.json"
    assert content_refs(record, _plant(record, edit))


def test_content_ref_walker_catches_a_local_fragment_ref_inside_a_content_schema() -> None:
    """A `#/$defs/...` ref resolves to the file it sits in, so it only matters in that file."""
    assert _target_of(REDACTED, load_schema(REDACTED), "#/$defs/secret_free_text") == (
        REDACTED,
        "/$defs/secret_free_text",
    )


@pytest.mark.parametrize("rel", NO_TEXT_SCHEMAS)
def test_no_text_property_at_any_depth(rel: str) -> None:
    owners = [rel, *sorted(reachable_from(rel))]
    stray = [(owner, p) for owner in owners for p in text_property_findings(load_schema(owner))]
    assert stray == []
    assert not (set(owners) & CONTENT_SCHEMAS)


def test_reachability_check_sees_through_refs() -> None:
    def edit(doc: dict[str, Any]) -> None:
        doc["properties"]["embedded"] = {
            "$ref": "../../interactions/v1/redacted-content.schema.json"
        }

    planted = _plant("interactions/v1/interaction-record.schema.json", edit)
    assert content_refs("interactions/v1/interaction-record.schema.json", planted)
    # The real graph, by contrast, never reaches a content schema from the record.
    assert (
        ref_target(
            "interactions/v1/interaction-record.schema.json",
            "detection-finding.schema.json",
        )[0]
        == "interactions/v1/detection-finding.schema.json"
    )


# ------------------------------------------------------------------ 5. credential names


@pytest.mark.parametrize("rel", CREDENTIAL_AREAS)
def test_governance_areas_declare_no_credential_like_names(rel: str) -> None:
    assert governance_credential_findings(rel) == []


def test_dedup_key_is_the_only_raw_walker_finding_and_is_digest_pinned() -> None:
    raw = [f for rel in CREDENTIAL_AREAS for f in credential_findings(rel)]
    assert raw
    assert all(f.endswith("/properties/dedup_key") for f in raw), raw
    for rel in CREDENTIAL_AREAS:
        for finding in credential_findings(rel):
            body = _resolve_property(load_schema(rel), finding.removeprefix(rel))
            assert body["pattern"] == DEDUP_PATTERN


@pytest.mark.parametrize(
    "rel", ["notifications/v1/notification.schema.json", "policy/v1/policy-violation.schema.json"]
)
def test_unpinned_dedup_key_is_still_flagged(rel: str) -> None:
    def edit(doc: dict[str, Any]) -> None:
        doc["properties"]["dedup_key"] = {"type": "string", "maxLength": 80}

    assert governance_credential_findings(rel, _plant(rel, edit))

    def wrong_pattern(doc: dict[str, Any]) -> None:
        doc["properties"]["dedup_key"]["pattern"] = "^[a-f0-9]{64}$"

    assert governance_credential_findings(rel, _plant(rel, wrong_pattern))


def test_pinned_dedup_key_is_exempt_but_other_credential_names_are_not() -> None:
    rel = "notifications/v1/notification.schema.json"

    def edit(doc: dict[str, Any]) -> None:
        doc["properties"]["client_secret"] = {"type": "string", "maxLength": 10}
        doc["properties"]["api_key"] = {"type": "string", "maxLength": 10}

    findings = governance_credential_findings(rel, _plant(rel, edit))
    assert len(findings) == 2
    assert not any("dedup_key" in f for f in findings)


# ------------------------------------------------------------------ 6. telemetry closed


def test_telemetry_event_is_closed_at_every_level() -> None:
    assert open_object_findings(load_schema(EVENT)) == []


def test_telemetry_event_top_level_properties_are_unchanged() -> None:
    assert list(load_schema(EVENT)["properties"]) == list(TELEMETRY_TOP_LEVEL)


def test_payload_ref_gained_only_the_six_named_members() -> None:
    members = list(load_schema(EVENT)["$defs"]["payload_ref"]["properties"])
    assert members == [*PAYLOAD_REF_PRE_PRP, *PAYLOAD_REF_ADDED]


def test_payload_ref_content_parts_items_are_closed_and_size_only() -> None:
    items = load_schema(EVENT)["$defs"]["payload_ref"]["properties"]["content_parts"]["items"]
    assert items["additionalProperties"] is False
    assert set(items["properties"]) == {"part", "char_count", "truncated"}


def test_open_object_walker_catches_planted_open_objects() -> None:
    def top(doc: dict[str, Any]) -> None:
        del doc["additionalProperties"]

    def nested(doc: dict[str, Any]) -> None:
        doc["$defs"]["payload_ref"]["properties"]["content_parts"]["items"][
            "additionalProperties"
        ] = True

    def fresh_def(doc: dict[str, Any]) -> None:
        doc["$defs"]["planted"] = {"type": "object", "properties": {"a": {"type": "string"}}}

    assert open_object_findings(_plant(EVENT, top)) == ["/"]
    assert open_object_findings(_plant(EVENT, nested)) == [
        "/$defs/payload_ref/properties/content_parts/items"
    ]
    assert open_object_findings(_plant(EVENT, fresh_def)) == ["/$defs/planted"]


# ------------------------------------------------------------------ 7. secret-free stored text


def test_redacted_text_resolves_to_secret_free_text_with_patterns() -> None:
    schema = load_schema(REDACTED)
    parts = schema["properties"]["parts"]["items"]
    part = resolve_pointer(schema, parts["$ref"].removeprefix("#")) if "$ref" in parts else parts
    text = part["properties"]["text"]
    assert text["$ref"] == "#/$defs/secret_free_text"
    body = resolve_pointer(schema, text["$ref"].removeprefix("#"))
    assert body["not"]["anyOf"]
    assert all("pattern" in branch for branch in body["not"]["anyOf"])


def test_interaction_record_never_references_secret_free_text() -> None:
    rel = "interactions/v1/interaction-record.schema.json"
    refs = [
        ref
        for sub in iter_subschemas(load_schema(rel))
        if isinstance(ref := sub.node.get("$ref"), str)
    ]
    assert refs
    assert not [ref for ref in refs if "secret_free_text" in ref or "redacted-content" in ref]


def test_secret_free_text_check_catches_a_stripped_not() -> None:
    def edit(doc: dict[str, Any]) -> None:
        doc["$defs"]["secret_free_text"]["not"]["anyOf"] = []

    planted = _plant(REDACTED, edit)
    assert not planted["$defs"]["secret_free_text"]["not"]["anyOf"]
