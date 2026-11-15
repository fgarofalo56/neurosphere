"""Admin v1 identity and common contracts (PRP-37 item 1).

The golden examples in ``admin/v1/examples`` are covered by the generic suites
(test_schemas, test_roundtrip, the TypeScript run). This module pins the rules the identity
console (PRP-39) relies on and their parity with the PRP-06 core models they map onto:

* privileged roles (admin, security_auditor) without ``expires_at`` are rejected, as
  ``PolicyRoleAssignment`` rejects them;
* ``ResourceGrantChange.expires_at`` is required, as on ``PolicyGrant``;
* principal ids match the canonical pseudonymous pattern (never a UPN or email) and reasons
  are machine codes, with the same patterns core uses;
* ``CredentialReference`` accepts exactly one of a Key Vault secret URI (Commercial or
  Government host) or a managed-identity client id.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

import pytest
from contract_support import SCHEMA_ROOT, load_json, load_schema, model_for, schema_errors
from neurosphere_core.auth.revocation.model import PRINCIPAL_ID_PATTERN, REASON_CODE_PATTERN
from neurosphere_core.auth.scope.policy import (
    CANONICAL_ID_PATTERN,
    PolicyGrant,
    PolicyRoleAssignment,
)
from pydantic import ValidationError
from validators import check_credential_reference_cloud

COMMON = "admin/v1/common.schema.json"
ROLE = "admin/v1/role-assignment-change.schema.json"
GRANT = "admin/v1/resource-grant-change.schema.json"
MEMBERSHIP = "admin/v1/domain-membership-change.schema.json"
CREDENTIAL = "admin/v1/credential-reference.schema.json"
REVOCATION = "admin/v1/revocation-request.schema.json"
STATUS = "admin/v1/revocation-status.schema.json"
SUMMARY = "admin/v1/principal-access-summary.schema.json"
EXAMPLES = SCHEMA_ROOT / "admin" / "v1" / "examples"


def _ex(name: str) -> dict[str, Any]:
    return load_json(EXAMPLES / "valid" / f"{name}.json")


def _defs() -> dict[str, Any]:
    return load_schema(COMMON)["$defs"]


def test_common_patterns_match_core() -> None:
    defs = _defs()
    assert defs["principal_id"]["pattern"] == PRINCIPAL_ID_PATTERN
    assert defs["reason_code"]["pattern"] == REASON_CODE_PATTERN
    assert defs["canonical_id"]["pattern"] == CANONICAL_ID_PATTERN
    assert defs["admin_kind"]["enum"] == [
        "producer",
        "connector_config",
        "domain",
        "budget",
        "price_sheet",
        "review_policy",
        "system_setting",
    ]


def test_roles_match_core() -> None:
    from neurosphere_core.auth.scope.permissions import Role

    assert set(_defs()["role"]["enum"]) == {r.value for r in Role}


@pytest.mark.parametrize("role", ["admin", "security_auditor"])
def test_privileged_assign_without_expiry_is_rejected_like_core(role: str) -> None:
    body = _ex("role-assignment-change.assign-admin-time-bound")
    body["role"] = role
    assert schema_errors(ROLE, body) == []
    del body["expires_at"]
    assert any(e.validator == "required" for e in schema_errors(ROLE, body))
    with pytest.raises(ValidationError, match="expires_at"):
        PolicyRoleAssignment(
            assignment_id=body["assignment_id"],
            role=role,  # type: ignore[arg-type]
            domain_ids=tuple(body["domain_ids"]),
        )


@pytest.mark.parametrize("role", ["viewer", "analyst", "domain_steward"])
def test_non_privileged_assign_may_be_open_ended(role: str) -> None:
    body = {**_ex("role-assignment-change.assign-viewer"), "role": role}
    assert schema_errors(ROLE, body) == []


def test_remove_needs_no_role() -> None:
    assert schema_errors(ROLE, _ex("role-assignment-change.remove")) == []
    assign = {**_ex("role-assignment-change.remove"), "op": "assign"}
    assert any(e.validator == "required" for e in schema_errors(ROLE, assign))


def test_assign_maps_onto_policy_role_assignment() -> None:
    body = _ex("role-assignment-change.assign-admin-time-bound")
    model = model_for(ROLE).model_validate(body)
    assignment = PolicyRoleAssignment(
        assignment_id=model.assignment_id.root,
        role=model.role.root,
        domain_ids=tuple(d.root for d in model.domain_ids),
        expires_at=datetime.fromisoformat(model.expires_at.root),
        reason=model.reason.root,
    )
    assert assignment.expires_at is not None and assignment.expires_at.tzinfo is not None


def test_pydantic_gap_on_privileged_expiry_is_visible() -> None:
    """The conditional lives only in JSON Schema (ADR-0004); PRP-65 validates it in core."""
    body = _ex("role-assignment-change.assign-admin-time-bound")
    del body["expires_at"]
    model_for(ROLE).model_validate(body)  # shape-valid
    assert schema_errors(ROLE, body)


def test_resource_grant_change_requires_expiry() -> None:
    assert "expires_at" in load_schema(GRANT)["required"]
    body = _ex("resource-grant-change.read-export")
    del body["expires_at"]
    assert schema_errors(GRANT, body)
    with pytest.raises(ValidationError):
        model_for(GRANT).model_validate(body)


def test_resource_grant_change_maps_onto_policy_grant() -> None:
    body = _ex("resource-grant-change.read-export")
    grant = PolicyGrant(
        grant_id=body["grant_id"],
        resource_id=body["resource_id"],
        permissions=tuple(body["permissions"]),
        expires_at=datetime.fromisoformat(body["expires_at"]),
        reason=body["reason"],
    )
    assert grant.expires_at > datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "principal_id",
    [
        "alice@contoso.com",
        "alice@contoso.onmicrosoft.com",
        "7f3c2b9e-0d4a-4c1e-9b7a-3e5f8d2c1a07",
        "commercial:contoso:entra:person:7f3c2b9e-0d4a-4c1e-9b7a-3e5f8d2c1a07",
        "commercial:contoso:entra:person:p-ABC",
        "commercial:contoso:entra:person:p-" + "a" * 63,
    ],
)
@pytest.mark.parametrize("rel", [ROLE, GRANT, MEMBERSHIP])
def test_principal_ids_are_pseudonymous(rel: str, principal_id: str) -> None:
    name = {
        ROLE: "role-assignment-change.assign-viewer",
        GRANT: "resource-grant-change.read-export",
        MEMBERSHIP: "domain-membership-change.add",
    }[rel]
    body = {**_ex(name), "principal_id": principal_id}
    assert any(e.validator == "pattern" for e in schema_errors(rel, body))
    with pytest.raises(ValidationError):
        model_for(rel).model_validate(body)


def test_government_principal_is_accepted() -> None:
    body = {
        **_ex("domain-membership-change.add"),
        "principal_id": "government:agency-a:entra:person:p-" + "7e" * 32,
        "domain_id": "government:agency-a:neurosphere:domain:benefits",
    }
    assert schema_errors(MEMBERSHIP, body) == []


def test_credential_reference_forms() -> None:
    kv = _ex("credential-reference.key-vault-secret")
    gov = _ex("credential-reference.government-key-vault")
    mi = _ex("credential-reference.managed-identity")
    for body in (kv, gov, mi):
        assert schema_errors(CREDENTIAL, body) == []
    assert ".vault.usgovcloudapi.net/" in gov["secret_uri"]
    both = {**kv, "managed_identity_client_id": mi["managed_identity_client_id"]}
    assert schema_errors(CREDENTIAL, both)
    neither = {"kind": "managed_identity"}
    assert schema_errors(CREDENTIAL, neither)


def test_check_credential_reference_cloud() -> None:
    kv = _ex("credential-reference.key-vault-secret")
    gov = _ex("credential-reference.government-key-vault")
    mi = _ex("credential-reference.managed-identity")
    assert check_credential_reference_cloud(kv, "commercial") == []
    assert check_credential_reference_cloud(gov, "government") == []
    assert check_credential_reference_cloud(kv, "government")
    assert check_credential_reference_cloud(gov, "commercial")
    assert check_credential_reference_cloud(mi, "government") == []
    assert check_credential_reference_cloud(kv, "china")


@pytest.mark.parametrize(
    "uri",
    [
        "https://kv-ns.vault.azure.net/secrets/x?api-version=7.4",
        "https://kv-ns.vault.azure.net.evil.example/secrets/x",
        "https://kv-ns.vault.azure.cn/secrets/x",
        "http://kv-ns.vault.azure.net/secrets/x",
        "https://user:pw@kv-ns.vault.azure.net/secrets/x",
        "https://kv-ns.vault.azure.net/keys/x",
        # Built at runtime so the secret scanners do not flag a fake connection string.
        ";".join(("DefaultEndpointsProtocol=https", "AccountName=a", "Account" + "Key=abc")),
    ],
)
def test_credential_reference_rejects_non_vault_values(uri: str) -> None:
    body = {"kind": "key_vault_secret", "secret_uri": uri}
    assert any(e.validator == "pattern" for e in schema_errors(CREDENTIAL, body))
    with pytest.raises(ValidationError):
        model_for(CREDENTIAL).model_validate(body)


def test_revocation_status_members_are_null_when_not_revoked() -> None:
    status = _ex("revocation-status.not-revoked")
    assert schema_errors(STATUS, status) == []
    revoked = _ex("revocation-status.revoked")
    for member in ("mode", "revoked_at", "reason", "revoked_by"):
        bad = copy.deepcopy(revoked)
        bad[member] = None
        assert schema_errors(STATUS, bad), member


def test_revocation_request_names_no_target() -> None:
    """The route names the principal; the body never can (no target spoofing)."""
    assert set(load_schema(REVOCATION)["properties"]) == {"schema_version", "reason", "mode"}


def test_access_summary_embeds_revocation_status() -> None:
    summary = _ex("principal-access-summary.typical")
    assert schema_errors(SUMMARY, summary) == []
    assert load_schema(SUMMARY)["properties"]["revocation"] == {
        "$ref": "revocation-status.schema.json"
    }
    for rel in (SUMMARY, STATUS):
        assert load_schema(rel).get("readOnly") is True
