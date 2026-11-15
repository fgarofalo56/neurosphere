"""No admin v1 contract can carry a credential value (PRP-37 item 1, A7).

The walker visits every property name declared anywhere in ``admin/v1`` (properties,
patternProperties and ``$defs`` bodies, at any depth) and fails on a name that looks like a
credential: a snake_case segment ``secret``, ``password``, ``passwd``, ``pwd``, ``token``,
``key``, ``apikey``, ``sas``, ``signature`` or ``connectionstring``. Explicit exceptions:

* ``secret_sha256``: a 64-hex digest (pattern-checked here), never the secret;
* ``ProducerSecretIssued.secret``: the response-only, shown-once producer secret (PRP-41);
* ``setting_key``: a lookup identifier, allowed only while it is enum-constrained.

Every admin object also forbids additional properties, so a credential cannot be smuggled in
under an undeclared name.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest
from contract_support import iter_subschemas, load_schema, schema_files

ADMIN = tuple(rel for rel in schema_files() if rel.startswith("admin/v1/"))
CREDENTIAL_SEGMENTS = frozenset(
    {
        "secret",
        "password",
        "passwd",
        "pwd",
        "token",
        "key",
        "apikey",
        "sas",
        "signature",
        "connectionstring",
    }
)
# Run-together spellings (camelCase or no separator) of the multi-word credential names.
CREDENTIAL_SUBSTRINGS = (
    "connectionstring",
    "apikey",
    "password",
    "passwd",
    "clientsecret",
    "accesskey",
    "accountkey",
    "sastoken",
)
HASH_PATTERN = "^[0-9a-f]{64}$"
# (schema, JSON Pointer of the property) -> why it is not a credential value.
ALLOWED: dict[tuple[str, str], str] = {
    (
        "admin/v1/producer-secret-issued.schema.json",
        "/properties/secret",
    ): "response-only, shown once at issue or rotation (PRP-41); never stored or re-read",
}
IDENTIFIER_NAMES = frozenset({"setting_key"})


def _declared_properties(rel: str) -> Iterator[tuple[str, str, dict[str, Any]]]:
    """``(pointer, property name, property schema)`` for every declared property."""
    for sub in iter_subschemas(load_schema(rel)):
        for keyword in ("properties", "patternProperties"):
            members = sub.node.get(keyword)
            if isinstance(members, dict):
                for name, body in members.items():
                    yield f"{sub.pointer}/{keyword}/{name}", name, body


def credential_like(name: str) -> bool:
    segments = {s for s in re.split(r"[^a-z0-9]+", name.lower()) if s}
    joined = re.sub(r"[^a-z0-9]", "", name.lower())
    camel = {s.lower() for s in re.findall(r"[a-z0-9]+|[A-Z][a-z0-9]*", name)}
    return bool((segments | camel) & CREDENTIAL_SEGMENTS) or any(
        word in joined for word in CREDENTIAL_SUBSTRINGS
    )


def credential_findings(rel: str, schema: dict[str, Any] | None = None) -> list[str]:
    document = schema if schema is not None else load_schema(rel)
    findings = []
    for sub in iter_subschemas(document):
        for keyword in ("properties", "patternProperties"):
            members = sub.node.get(keyword)
            if not isinstance(members, dict):
                continue
            for name, body in members.items():
                pointer = f"{sub.pointer}/{keyword}/{name}"
                if not credential_like(name):
                    continue
                if name == "secret_sha256" and _is_hash(body, document):
                    continue
                if (rel, pointer) in ALLOWED:
                    continue
                if name in IDENTIFIER_NAMES and _enum_constrained(body):
                    continue
                if name == "secret_uri" and _is_vault_reference(body, document):
                    continue
                findings.append(f"{rel}{pointer}")
    return findings


def _resolve_local(body: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    ref = body.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        return document["$defs"][ref.removeprefix("#/$defs/")]
    if isinstance(ref, str) and ref.startswith("common.schema.json#/$defs/"):
        return load_schema("admin/v1/common.schema.json")["$defs"][ref.rsplit("/", 1)[-1]]
    return body


def _is_hash(body: dict[str, Any], document: dict[str, Any]) -> bool:
    return _resolve_local(body, document).get("pattern") == HASH_PATTERN


def _is_vault_reference(body: dict[str, Any], document: dict[str, Any]) -> bool:
    """``secret_uri`` names a Key Vault secret identifier, pattern-bound to the vault hosts."""
    pattern = _resolve_local(body, document).get("pattern", "")
    return pattern.startswith("^https://") and "\\.vault\\.(azure\\.net|usgovcloudapi" in pattern


def _enum_constrained(body: dict[str, Any]) -> bool:
    return isinstance(body.get("enum"), list) or "const" in body


def test_admin_family_exists() -> None:
    assert "admin/v1/credential-reference.schema.json" in ADMIN
    assert len(ADMIN) >= 8


@pytest.mark.parametrize("rel", ADMIN)
def test_no_property_can_hold_a_credential_value(rel: str) -> None:
    assert credential_findings(rel) == []


def test_allowlist_entries_exist() -> None:
    """A stale allowlist entry would silently allow a future field of the same name."""
    present = {
        (rel, pointer)
        for rel in ADMIN
        for pointer, _, _ in _declared_properties(rel)
        if (rel, pointer) in ALLOWED
    }
    missing = set(ALLOWED) - present
    if missing and not any(rel == "admin/v1/producer-secret-issued.schema.json" for rel in ADMIN):
        pytest.skip("producer-secret-issued lands in item 2")
    assert not missing, missing


@pytest.mark.parametrize(
    "name",
    [
        "client_secret",
        "secret",
        "api_key",
        "apiKey",
        "access_token",
        "password",
        "sas",
        "storage_connection_string",
        "connectionString",
        "signing_key",
    ],
)
def test_walker_catches_planted_credential_fields(name: str) -> None:
    planted = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"ok": {"type": "string"}, name: {"type": "string"}},
        "$defs": {"nested": {"type": "object", "properties": {name: {"type": "string"}}}},
    }
    findings = credential_findings("admin/v1/planted.schema.json", planted)
    assert len(findings) == 2, findings


def test_walker_allows_hash_but_not_plain_secret_sha256() -> None:
    hashed = {"properties": {"secret_sha256": {"type": "string", "pattern": HASH_PATTERN}}}
    assert credential_findings("admin/v1/x.schema.json", hashed) == []
    loose = {"properties": {"secret_sha256": {"type": "string"}}}
    assert credential_findings("admin/v1/x.schema.json", loose)


def test_identifier_key_must_stay_enum_constrained() -> None:
    loose = {"properties": {"setting_key": {"type": "string"}}}
    assert credential_findings("admin/v1/x.schema.json", loose)
    closed = {"properties": {"setting_key": {"type": "string", "enum": ["copilot"]}}}
    assert credential_findings("admin/v1/x.schema.json", closed) == []


@pytest.mark.parametrize("rel", ADMIN)
def test_every_admin_object_is_closed(rel: str) -> None:
    open_objects = [
        sub.pointer or "/"
        for sub in iter_subschemas(load_schema(rel))
        if "properties" in sub.node
        and not sub.under_conditional
        and sub.node.get("additionalProperties") is not False
    ]
    assert not open_objects, open_objects
