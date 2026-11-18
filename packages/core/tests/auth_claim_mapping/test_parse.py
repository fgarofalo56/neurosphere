"""PRP-138 item 1: ``parse_claim_role_mapping`` is strict and never echoes its input."""

from __future__ import annotations

import json
from typing import Any

import pytest
from neurosphere_core.auth.scope.claim_mapping import (
    MAPPABLE_ROLES,
    MAPPED_ISSUER_KINDS,
    ClaimRoleMapping,
    ClaimRoleMappingError,
    parse_claim_role_mapping,
)
from neurosphere_core.auth.scope.permissions import Role

TENANT = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"
AUDIENCE = "api://neurosphere-test-api"
GROUP = "6C1D2E3F-4A5B-4C6D-8E7F-90A1B2C3D4E5"
FINANCE = "commercial:contoso:catalog:domain:finance"


def entry(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "ns-admins",
        "claim": "roles",
        "value": "admin",
        "role": "admin",
        "domains": "all",
        "customer_control": True,
    }
    base.update(overrides)
    return base


def document(*entries: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "tenant_id": TENANT,
        "audience": AUDIENCE,
        "entries": list(entries) if entries else [entry()],
    }
    base.update(overrides)
    return base


def refuse(raw: str, reason: str) -> None:
    with pytest.raises(ClaimRoleMappingError) as caught:
        parse_claim_role_mapping(raw)
    assert caught.value.reason == reason
    assert isinstance(caught.value, ValueError)


def refuse_doc(doc: Any, reason: str) -> None:
    refuse(json.dumps(doc), reason)


# --- off --------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [None, "", "   ", "\n\t "])
def test_unset_empty_or_blank_means_off(raw: str | None) -> None:
    assert parse_claim_role_mapping(raw) is None


# --- happy path -------------------------------------------------------------------------------


def test_happy_path_parses_frozen_model() -> None:
    raw = json.dumps(
        document(
            entry(),
            entry(
                id="finance-readers",
                claim="groups",
                value=GROUP,
                role="viewer",
                domains=[FINANCE],
                customer_control=False,
            ),
            entry(id="auditors", value="Security.Auditor", role="security_auditor"),
        )
    )
    mapping = parse_claim_role_mapping(raw)
    assert isinstance(mapping, ClaimRoleMapping)
    assert mapping.tenant_id == TENANT
    assert mapping.audience == AUDIENCE
    assert [e.id for e in mapping.entries] == ["ns-admins", "finance-readers", "auditors"]
    admins, readers, auditors = mapping.entries
    assert admins.role is Role.ADMIN
    assert admins.domains == "all"
    assert admins.customer_control is True
    assert readers.claim == "groups"
    assert readers.value == GROUP.lower()
    assert readers.domains == (FINANCE,)
    assert auditors.value == "Security.Auditor"
    with pytest.raises(ValueError, match="frozen"):
        mapping.audience = "other"  # type: ignore[misc]


def test_uppercase_tenant_is_normalised() -> None:
    mapping = parse_claim_role_mapping(json.dumps(document(tenant_id=TENANT.upper())))
    assert mapping is not None
    assert mapping.tenant_id == TENANT


def test_same_value_twice_with_same_role_is_allowed() -> None:
    raw = json.dumps(
        document(entry(), entry(id="ns-admins-finance", domains=[FINANCE], customer_control=False))
    )
    mapping = parse_claim_role_mapping(raw)
    assert mapping is not None
    assert len(mapping.entries) == 2


def test_thirty_two_entries_is_the_limit() -> None:
    entries = [entry(id=f"e-{i}", value=f"role-{i}") for i in range(32)]
    mapping = parse_claim_role_mapping(json.dumps(document(*entries)))
    assert mapping is not None
    assert len(mapping.entries) == 32


def test_constants_are_closed() -> None:
    assert {r.value for r in MAPPABLE_ROLES} == {
        "viewer",
        "analyst",
        "domain_steward",
        "admin",
        "security_auditor",
    }
    assert frozenset({"entra"}) == MAPPED_ISSUER_KINDS


# --- refusals -------------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["{", "not json", '{"tenant_id": }', "[1,"])
def test_malformed_json(raw: str) -> None:
    refuse(raw, "malformed_json")


@pytest.mark.parametrize("raw", ["[]", '"text"', "42", "null", "true"])
def test_non_object(raw: str) -> None:
    refuse(raw, "not_an_object")


def test_duplicate_json_key() -> None:
    raw = f'{{"tenant_id": "{TENANT}", "tenant_id": "{TENANT}", "audience": "a", "entries": []}}'
    refuse(raw, "duplicate_key")


def test_unknown_top_level_key() -> None:
    refuse_doc(document(cloud="commercial"), "unknown_key")


def test_unknown_entry_key() -> None:
    refuse_doc(document(entry(expires_at="2030-01-01T00:00:00Z")), "unknown_key")


@pytest.mark.parametrize("key", ["tenant_id", "audience", "entries"])
def test_missing_top_level_key(key: str) -> None:
    doc = document()
    del doc[key]
    refuse_doc(doc, "missing_key")


@pytest.mark.parametrize("key", ["id", "claim", "value", "role", "domains", "customer_control"])
def test_missing_entry_key(key: str) -> None:
    item = entry()
    del item[key]
    refuse_doc(document(item), "missing_key")


@pytest.mark.parametrize("entries", [[], {}, "ns-admins"])
def test_entries_not_a_non_empty_list(entries: Any) -> None:
    refuse_doc(document(entries=entries), "invalid_entries")


def test_entry_not_an_object() -> None:
    refuse_doc(document(entries=["ns-admins"]), "invalid_entry")


def test_more_than_thirty_two_entries() -> None:
    entries = [entry(id=f"e-{i}", value=f"role-{i}") for i in range(33)]
    refuse_doc(document(*entries), "too_many_entries")


@pytest.mark.parametrize(
    "entry_id", ["", "Admins", "1admins", "-admins", "ns_admins", "a" * 64, "ns admins", 7]
)
def test_entry_id_pattern(entry_id: Any) -> None:
    refuse_doc(document(entry(id=entry_id)), "invalid_entry_id")


def test_entry_id_with_trailing_newline_is_refused() -> None:
    refuse_doc(document(entry(id="admins\n")), "invalid_entry_id")


def test_duplicate_entry_id() -> None:
    refuse_doc(document(entry(), entry(value="other")), "duplicate_entry_id")


@pytest.mark.parametrize(
    "role_name", ["owner", "Admin", "interaction_investigator", "", None, ["admin"]]
)
def test_role_not_mappable(role_name: Any) -> None:
    refuse_doc(document(entry(role=role_name)), "unmappable_role")


@pytest.mark.parametrize("claim", ["wids", "Roles", "scp", "", None])
def test_claim_kind(claim: Any) -> None:
    refuse_doc(document(entry(claim=claim)), "invalid_claim_kind")


@pytest.mark.parametrize(
    "value",
    ["admins", "6c1d2e3f4a5b4c6d8e7f90a1b2c3d4e5", "{6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5}", 5],
)
def test_group_value_not_a_guid(value: Any) -> None:
    refuse_doc(document(entry(claim="groups", value=value)), "invalid_group_value")


@pytest.mark.parametrize("value", ["", "has space", "a" * 121, "admin\n", "admin*", 1, None])
def test_role_value_pattern(value: Any) -> None:
    refuse_doc(document(entry(value=value)), "invalid_role_value")


def test_one_value_mapped_to_two_roles() -> None:
    refuse_doc(
        document(entry(), entry(id="ns-viewers", role="viewer")),
        "conflicting_value_role",
    )


def test_one_group_mapped_to_two_roles_across_case() -> None:
    refuse_doc(
        document(
            entry(id="g-one", claim="groups", value=GROUP),
            entry(id="g-two", claim="groups", value=GROUP.lower(), role="viewer"),
        ),
        "conflicting_value_role",
    )


@pytest.mark.parametrize(
    "domains",
    [
        "ALL",
        "",
        [],
        None,
        True,
        ["finance"],
        ["commercial:contoso:catalog:agent:finance"],
        ["commercial:Contoso:catalog:domain:finance"],
        ["azure:contoso:catalog:domain:finance"],
        [FINANCE, FINANCE],
        [FINANCE, 3],
        {"all": True},
    ],
)
def test_domains_invalid(domains: Any) -> None:
    refuse_doc(document(entry(domains=domains)), "invalid_domains")


@pytest.mark.parametrize("value", ["true", 1, 0, None])
def test_customer_control_not_bool(value: Any) -> None:
    refuse_doc(document(entry(customer_control=value)), "invalid_customer_control")


@pytest.mark.parametrize(
    "tenant_id", ["contoso.onmicrosoft.com", "common", "", None, "0f1e2d3c4b5a49688776a5b4c3d2e1f0"]
)
def test_tenant_not_a_guid(tenant_id: Any) -> None:
    refuse_doc(document(tenant_id=tenant_id), "invalid_tenant_id")


@pytest.mark.parametrize("audience", ["", "   ", " api://x", "api://*", None, 3])
def test_audience_invalid(audience: Any) -> None:
    refuse_doc(document(audience=audience), "invalid_audience")


def test_error_never_echoes_input() -> None:
    hidden_group = "0a0b0c0d-1111-4222-8333-944455556666"
    raw = json.dumps(
        document(
            entry(id="g-one", claim="groups", value=hidden_group),
            entry(id="g-two", claim="groups", value=hidden_group, role="viewer"),
        )
    )
    with pytest.raises(ClaimRoleMappingError) as caught:
        parse_claim_role_mapping(raw)
    assert hidden_group not in str(caught.value)
    assert caught.value.__cause__ is None
