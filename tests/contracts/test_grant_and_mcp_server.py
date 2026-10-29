"""Grant, McpServer and GRANTS_ACCESS_TO contract conformance (PRP-33 item 5).

The golden examples live with the other catalog examples (``catalog/v1/examples``) so the
generic suites already cover them: test_schemas (JSON Schema, single expected error),
test_roundtrip (Pydantic round trip, Python validators, the TypeScript run) and
tests/contracts/ts/*.test.ts (tsc against the generated types). This module pins the
behaviour specific to these contracts:

* MCP grants are call-limited only: any token or request limit on an MCP target is invalid,
  and model targets carry no MCP call limit;
* ``token_quota`` and ``quota_period`` are set together;
* ``target.ref`` carries the type segment ``target.kind`` names;
* a user principal carries no display label;
* the MCP URL is https, ends in ``/mcp`` and carries no user info, query or fragment;
* an SSE-only server or an API-key upstream is never publishable.

The cross-field rules are JSON Schema conditionals, which the generated Pydantic model does
not carry (ADR-0004); the tests assert both halves of that statement so the gap stays visible.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import pytest
from contract_support import (
    CONTRACTS_DIR,
    SCHEMA_ROOT,
    load_json,
    model_for,
    schema_errors,
    valid_cases,
)
from pydantic import ValidationError
from validators import (
    canonical_id_fullmatches,
    run_single_document_validators,
    validate_grant_window,
    validate_mcp_tool_names_unique,
)

GRANT = "catalog/v1/grant.schema.json"
MCP = "catalog/v1/mcp_server.schema.json"
EDGE = "catalog/v1/grants_access_to.schema.json"
EXAMPLES = SCHEMA_ROOT / "catalog" / "v1" / "examples"

GRANT_USER = "valid/grant.user-model-deployment-token-limits.json"
GRANT_MCP = "valid/grant.entra-group-mcp-calls.json"
MCP_ENTRA = "valid/mcp_server.entra-streamable-http.json"
MCP_API_KEY = "valid/mcp_server.api-key-not-publishable.json"
EDGE_ASSERTED = "valid/grants_access_to.asserted.json"

GOLDEN = {
    GRANT_USER: GRANT,
    GRANT_MCP: GRANT,
    MCP_ENTRA: MCP,
    MCP_API_KEY: MCP,
    EDGE_ASSERTED: EDGE,
}


def _ex(rel: str) -> dict[str, Any]:
    return copy.deepcopy(load_json(EXAMPLES / rel))


def _pydantic_accepts(schema: str, document: Any) -> bool:
    try:
        model_for(schema).model_validate(document)
    except ValidationError:
        return False
    return True


def _errors(schema: str, document: Any) -> list[tuple[str, str]]:
    """``(instance pointer, keyword)`` of each top-level JSON Schema error, sorted."""
    return sorted(
        ("/" + "/".join(map(str, e.absolute_path)), str(e.validator))
        for e in schema_errors(schema, document)
    )


# --------------------------------------------------------------------------- golden examples


def test_golden_examples_are_registered_in_the_catalog_manifest() -> None:
    listed = {c.file.resolve(): c.schema for c in valid_cases()}
    for rel, schema in GOLDEN.items():
        assert listed.get((EXAMPLES / rel).resolve()) == schema, rel


@pytest.mark.parametrize(("rel", "schema"), sorted(GOLDEN.items()))
def test_golden_example_round_trips_through_pydantic(
    rel: str, schema: str, validator_context: dict[str, Any]
) -> None:
    document = _ex(rel)
    assert schema_errors(schema, document) == []
    model = model_for(schema).model_validate(document)
    assert model.model_dump(mode="json", by_alias=True, exclude_unset=True) == document
    assert run_single_document_validators(schema, document, validator_context) == []


@pytest.mark.parametrize("rel", [GRANT_USER, GRANT_MCP, MCP_ENTRA, MCP_API_KEY])
def test_entity_id_type_segment_equals_entity_type(rel: str) -> None:
    document = _ex(rel)
    assert canonical_id_fullmatches(document["id"])
    assert document["id"].split(":")[3] == document["entity_type"]


def test_unset_limits_default_to_null_never_zero() -> None:
    grant = model_for(GRANT).model_validate(_ex(GRANT_MCP))
    limits = grant.limits.model_dump(mode="json")
    assert limits == {
        "tokens_per_minute": None,
        "token_quota": None,
        "quota_period": None,
        "requests_per_minute": None,
        "mcp_calls_per_minute": 60,
    }


def test_edge_joins_the_golden_grant_to_its_target() -> None:
    edge, grant = _ex(EDGE_ASSERTED), _ex(GRANT_MCP)
    assert edge["source_id"] == grant["id"]
    assert edge["target_id"] == grant["target"]["ref"] == _ex(MCP_ENTRA)["id"]


# --------------------------------------------------------------------------- grant limits


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tokens_per_minute", 1000),
        ("token_quota", 100000),
        ("quota_period", "day"),
        ("requests_per_minute", 30),
    ],
)
def test_mcp_grant_with_token_or_request_limits_is_invalid(field: str, value: object) -> None:
    grant = _ex(GRANT_MCP)
    grant["limits"][field] = value
    assert (f"/limits/{field}", "type") in _errors(GRANT, grant)
    # Pydantic carries the shape only (ADR-0004): the conditional lives in JSON Schema.
    assert _pydantic_accepts(GRANT, grant)


def test_mcp_grant_with_both_token_quota_fields_is_still_invalid() -> None:
    grant = _ex(GRANT_MCP)
    grant["limits"].update({"token_quota": 100000, "quota_period": "day"})
    errors = _errors(GRANT, grant)
    assert ("/limits/token_quota", "type") in errors
    assert ("/limits/quota_period", "type") in errors


@pytest.mark.parametrize("kind", ["model_deployment", "model_api"])
def test_model_grant_with_an_mcp_call_limit_is_invalid(kind: str) -> None:
    grant = _ex(GRANT_USER)
    if kind == "model_api":
        grant["target"] = {"kind": "model_api", "ref": "commercial:contoso:apim:service:llm-api"}
    assert _errors(GRANT, grant) == []
    grant["limits"]["mcp_calls_per_minute"] = 10
    assert _errors(GRANT, grant) == [("/limits/mcp_calls_per_minute", "type")]


def test_token_quota_needs_its_period_and_the_period_needs_a_quota() -> None:
    grant = _ex(GRANT_USER)
    del grant["limits"]["quota_period"]
    assert _errors(GRANT, grant) == [("/limits", "required")]
    grant["limits"]["quota_period"] = None
    assert _errors(GRANT, grant) == [("/limits/quota_period", "type")]

    grant = _ex(GRANT_USER)
    grant["limits"]["token_quota"] = None
    assert _errors(GRANT, grant) == [("/limits/token_quota", "type")]
    del grant["limits"]["token_quota"]
    assert _errors(GRANT, grant) == [("/limits", "required")]

    grant["limits"]["quota_period"] = None
    assert _errors(GRANT, grant) == []


@pytest.mark.parametrize("field", ["tokens_per_minute", "token_quota", "requests_per_minute"])
@pytest.mark.parametrize("value", [0, -1, 1.5, "100", True])
def test_limits_are_positive_integers(field: str, value: object) -> None:
    grant = _ex(GRANT_USER)
    grant["limits"][field] = value
    assert schema_errors(GRANT, grant)
    assert not _pydantic_accepts(GRANT, grant)


def test_limits_reject_unknown_members() -> None:
    grant = _ex(GRANT_USER)
    grant["limits"]["tokens_per_hour"] = 10
    assert ("/limits", "additionalProperties") in _errors(GRANT, grant)
    assert not _pydantic_accepts(GRANT, grant)


# --------------------------------------------------------------------------- grant target


@pytest.mark.parametrize(
    ("kind", "ref", "ok"),
    [
        ("model_deployment", "commercial:contoso:foundry:model_deployment:gpt-4o-prod", True),
        ("model_api", "commercial:contoso:apim:service:llm-api", True),
        ("mcp_server", "commercial:contoso:neurosphere:mcp_server:finance/ledger-tools", True),
        ("model_deployment", "commercial:contoso:neurosphere:mcp_server:finance/ledger", False),
        ("model_api", "commercial:contoso:foundry:model_deployment:gpt-4o-prod", False),
        ("mcp_server", "commercial:contoso:apim:service:llm-api", False),
    ],
)
def test_target_ref_type_segment_follows_target_kind(kind: str, ref: str, ok: bool) -> None:
    grant = _ex(GRANT_USER) if kind != "mcp_server" else _ex(GRANT_MCP)
    grant["target"] = {"kind": kind, "ref": ref}
    errors = _errors(GRANT, grant)
    assert (errors == []) is ok, errors
    if not ok:
        assert errors == [("/target/ref", "pattern")]


@pytest.mark.parametrize(
    "ref",
    [
        "commercial:contoso:foundry:agent:support-bot",
        "commercial:contoso:foundry:tool:lookup",
        "commercial:contoso:foundry:model_deployment:a:b",
        "grant:finance:analyst-gpt-4o",
    ],
)
def test_target_ref_outside_the_three_types_is_rejected_by_every_engine(ref: str) -> None:
    grant = _ex(GRANT_USER)
    grant["target"]["ref"] = ref
    assert schema_errors(GRANT, grant)
    assert not _pydantic_accepts(GRANT, grant)


def test_government_grant_cannot_target_a_commercial_entity() -> None:
    grant = _ex(GRANT_USER)
    grant["cloud"] = "government"
    grant["id"] = grant["id"].replace("commercial:", "government:", 1)
    grant["domain_id"] = grant["domain_id"].replace("commercial:", "government:", 1)
    errors = _errors(GRANT, grant)
    assert errors == [("/target/ref", "anyOf")]
    grant["target"]["ref"] = grant["target"]["ref"].replace("commercial:", "government:", 1)
    assert _errors(GRANT, grant) == []


# --------------------------------------------------------------------------- grant principal


def test_user_principal_carries_no_display_label() -> None:
    grant = _ex(GRANT_USER)
    grant["principal"]["display"] = "Analyst seat"
    assert _errors(GRANT, grant) == [("/principal/display", "type")]
    del grant["principal"]["display"]
    assert _errors(GRANT, grant) == []


@pytest.mark.parametrize("kind", ["application", "agent", "entra_group"])
def test_non_user_principals_may_carry_a_display_label(kind: str) -> None:
    grant = _ex(GRANT_USER)
    grant["principal"] = {
        "kind": kind,
        "object_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        "display": "finance-batch",
    }
    assert _errors(GRANT, grant) == []


@pytest.mark.parametrize(
    "object_id",
    [
        "AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE",
        "aaaaaaaabbbb4ccc8dddeeeeeeeeeeee",
        "{aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee}",
        "user@contoso.example",
        "",
    ],
)
def test_principal_object_id_is_a_lowercase_guid(object_id: str) -> None:
    grant = _ex(GRANT_USER)
    grant["principal"]["object_id"] = object_id
    assert schema_errors(GRANT, grant)
    assert not _pydantic_accepts(GRANT, grant)


def test_principal_kind_is_closed() -> None:
    grant = _ex(GRANT_USER)
    grant["principal"]["kind"] = "service_principal"
    assert ("/principal/kind", "enum") in _errors(GRANT, grant)
    assert not _pydantic_accepts(GRANT, grant)


# --------------------------------------------------------------------------- grant misc


@pytest.mark.parametrize("value", ["CC-4410", "finops/eu.1", "A"])
def test_cost_center_accepts_header_safe_values(value: str) -> None:
    grant = _ex(GRANT_USER)
    grant["cost_center"] = value
    assert _errors(GRANT, grant) == []


@pytest.mark.parametrize("value", ["", " CC", "CC 4410", "cc\n", "-lead", "x" * 129])
def test_cost_center_rejects_unsafe_values(value: str) -> None:
    grant = _ex(GRANT_USER)
    grant["cost_center"] = value
    assert not _pydantic_accepts(GRANT, grant)
    if not value.endswith("\n"):  # jsonschema uses re.search; '$' matches before a newline
        assert schema_errors(GRANT, grant)


def test_validate_grant_window() -> None:
    grant = _ex(GRANT_USER)
    assert validate_grant_window(grant) == []
    grant["valid_until"] = grant["valid_from"]
    assert validate_grant_window(grant)
    grant["valid_until"] = "2026-10-01T00:00:00Z"
    assert validate_grant_window(grant)
    grant["valid_until"] = None
    assert validate_grant_window(grant) == []
    grant["valid_from"] = None
    grant["valid_until"] = "2026-10-01T00:00:00Z"
    assert validate_grant_window(grant) == []


def test_grant_requires_enabled_and_provenance() -> None:
    for member in ("enabled", "provenance", "limits", "principal", "target"):
        grant = _ex(GRANT_USER)
        del grant[member]
        assert ("/", "required") in _errors(GRANT, grant), member


# --------------------------------------------------------------------------- MCP server URL


@pytest.mark.parametrize(
    "url",
    [
        "https://ledger-tools.contoso.example/mcp",
        "https://apim-contoso.azure-api.net/ledger/mcp",
        "https://ledger.contoso.example:8443/v1/tools/mcp",
        "https://10.0.0.4/mcp",
        "https://ledger.contoso.example/a%20b/mcp",
    ],
)
def test_mcp_url_accepts_streamable_http_endpoints(url: str) -> None:
    server = _ex(MCP_ENTRA)
    server["url"] = url
    assert _errors(MCP, server) == []
    assert _pydantic_accepts(MCP, server)


@pytest.mark.parametrize(
    ("url", "why"),
    [
        ("https://ledger-tools.contoso.example/api", "path does not end in /mcp"),
        ("https://ledger-tools.contoso.example/mcp/", "trailing slash after /mcp"),
        ("https://ledger-tools.contoso.example/mcp?code=abc", "query string"),
        ("https://ledger-tools.contoso.example/mcp?", "empty query string"),
        ("https://ledger-tools.contoso.example/mcp#frag", "fragment"),
        ("http://ledger-tools.contoso.example/mcp", "plain http"),
        ("https://user:secret@ledger.contoso.example/mcp", "user info with password"),
        ("https://user@ledger.contoso.example/mcp", "user info"),
        ("https://Ledger.Contoso.example/mcp", "uppercase host"),
        ("https:///mcp", "no host"),
        ("https://ledger.contoso.example/sse", "SSE endpoint path"),
        ("https://ledger.contoso.example/mcp\n", "trailing newline"),
        ("https://ledger.contoso.example/x mcp", "whitespace"),
    ],
)
def test_mcp_url_rejects_everything_else(url: str, why: str) -> None:
    server = _ex(MCP_ENTRA)
    server["url"] = url
    pattern = load_json(SCHEMA_ROOT / MCP)["properties"]["url"]["pattern"]
    assert re.fullmatch(pattern, url) is None, why
    assert not _pydantic_accepts(MCP, server), why
    if not url.endswith("\n"):  # jsonschema uses re.search; '$' matches before a newline
        assert _errors(MCP, server) == [("/url", "pattern")], why


# --------------------------------------------------------------------------- publishable


def test_api_key_upstream_is_representable_but_never_publishable() -> None:
    server = _ex(MCP_API_KEY)
    assert server["auth"]["kind"] == "api_key" and server["publishable"] is False
    assert _errors(MCP, server) == []
    server["publishable"] = True
    assert _errors(MCP, server) == [("/publishable", "const")]
    assert _pydantic_accepts(MCP, server)  # conditional: JSON Schema only (ADR-0004)


def test_sse_transport_is_representable_but_never_publishable() -> None:
    server = _ex(MCP_ENTRA)
    server["transport"] = "sse"
    assert _errors(MCP, server) == [("/publishable", "const")]
    server["publishable"] = False
    assert _errors(MCP, server) == []


@pytest.mark.parametrize("kind", ["entra", "managed_identity", "none"])
def test_streamable_http_without_api_key_may_be_publishable(kind: str) -> None:
    server = _ex(MCP_ENTRA)
    server["auth"] = {"kind": kind, "audience": None}
    assert _errors(MCP, server) == []


def test_auth_carries_no_credential_member() -> None:
    server = _ex(MCP_API_KEY)
    server["auth"]["api_key"] = "not-a-real-key"
    assert ("/auth", "additionalProperties") in _errors(MCP, server)
    assert not _pydantic_accepts(MCP, server)


# --------------------------------------------------------------------------- tools


def test_validate_mcp_tool_names_unique() -> None:
    server = _ex(MCP_ENTRA)
    assert validate_mcp_tool_names_unique(server) == []
    server["tools"].append({"name": "lookup_invoice", "description": "duplicate"})
    assert schema_errors(MCP, server) == []  # uniqueItems compares whole objects
    assert validate_mcp_tool_names_unique(server) == [
        "tools: name 'lookup_invoice' appears 2 times"
    ]


@pytest.mark.parametrize("name", ["", "has space", "slash/name", "x" * 129, "naïve"])
def test_tool_name_uses_the_mcp_character_set(name: str) -> None:
    server = _ex(MCP_ENTRA)
    server["tools"][1]["name"] = name
    assert schema_errors(MCP, server)
    assert not _pydantic_accepts(MCP, server)


def test_tool_annotations_are_closed_and_snake_case() -> None:
    server = _ex(MCP_ENTRA)
    server["tools"][0]["annotations"]["readOnlyHint"] = True
    assert ("/tools/0/annotations", "additionalProperties") in _errors(MCP, server)
    assert not _pydantic_accepts(MCP, server)


@pytest.mark.parametrize("version", ["2025-6-18", "v2025-06-18", "latest", "2025-06-18T00:00:00Z"])
def test_protocol_versions_are_dates(version: str) -> None:
    server = _ex(MCP_ENTRA)
    server["protocol_versions"] = [version]
    assert schema_errors(MCP, server)
    assert not _pydantic_accepts(MCP, server)


def test_owner_id_must_be_an_owner_in_the_same_cloud() -> None:
    server = _ex(MCP_ENTRA)
    server["owner_id"] = "commercial:contoso:entra:person:psn_0123456789abcdef"
    assert schema_errors(MCP, server)
    server["owner_id"] = "government:contoso:neurosphere:owner:team-payments"
    assert _errors(MCP, server) == [("/owner_id", "anyOf")]


# --------------------------------------------------------------------------- edge


@pytest.mark.parametrize(
    "target",
    [
        "commercial:contoso:apim:service:llm-api",
        "commercial:contoso:foundry:model_deployment:gpt-4o-prod",
        "commercial:contoso:neurosphere:mcp_server:finance/ledger-tools",
    ],
)
def test_grants_access_to_targets_the_three_grantable_types(target: str) -> None:
    edge = _ex(EDGE_ASSERTED)
    edge["target_id"] = target
    assert _errors(EDGE, edge) == []


@pytest.mark.parametrize(
    "target",
    ["commercial:contoso:foundry:agent:support-bot", "commercial:contoso:foundry:tool:x"],
)
def test_grants_access_to_rejects_other_targets(target: str) -> None:
    edge = _ex(EDGE_ASSERTED)
    edge["target_id"] = target
    assert _errors(EDGE, edge) == [("/target_id", "pattern")]
    assert not _pydantic_accepts(EDGE, edge)


# --------------------------------------------------------------------------- enumerations


def test_enumerations_carry_the_new_types() -> None:
    common = load_json(SCHEMA_ROOT / "catalog/v1/common.schema.json")["$defs"]
    assert {"grant", "mcp_server"} <= set(common["entity_type"]["enum"])
    assert "grants_access_to" in common["relation_type"]["enum"]
    alias = load_json(SCHEMA_ROOT / "catalog/v1/alias.schema.json")["properties"]
    # Alias rule: every entity type except person (person aliases are re-identification data).
    assert set(alias["entity_type"]["enum"]) == set(common["entity_type"]["enum"]) - {"person"}


def test_typescript_index_exports_the_new_root_types() -> None:
    index = (CONTRACTS_DIR / "ts" / "src" / "index.ts").read_text(encoding="utf-8")
    for name, stem in (
        ("Grant", "grant"),
        ("McpServer", "mcp_server"),
        ("GrantsAccessToRelation", "grants_access_to"),
    ):
        assert f'export type {{ {name} }} from "./catalog/v1/{stem}.js";' in index
    assert Path(CONTRACTS_DIR / "ts" / "src" / "catalog" / "v1" / "grant.ts").is_file()
