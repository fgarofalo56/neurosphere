"""PRP-138 item 1: ``matching_entries`` maps only bound, delegated Entra user tokens."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from neurosphere_core.auth.jwt import VerifiedClaims
from neurosphere_core.auth.jwt.config import dev_issuer_for
from neurosphere_core.auth.scope.claim_mapping import (
    ClaimRoleMapping,
    matching_entries,
    parse_claim_role_mapping,
)
from neurosphere_core.cloud import CloudName

TENANT = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"
OTHER_TENANT = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
AUDIENCE = "api://neurosphere-test-api"
OBJECT_ID = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"
GROUP = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
OTHER_GROUP = "2b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e"
T0 = datetime(2027, 1, 1, tzinfo=UTC)


class OverageClaims(VerifiedClaims):
    """Stand-in until item 2 adds ``groups_overage`` to ``VerifiedClaims`` itself."""

    groups_overage: bool = False


def mapping() -> ClaimRoleMapping:
    raw = {
        "tenant_id": TENANT,
        "audience": AUDIENCE,
        "entries": [
            {
                "id": "ns-admins",
                "claim": "roles",
                "value": "admin",
                "role": "admin",
                "domains": "all",
                "customer_control": True,
            },
            {
                "id": "ns-analysts",
                "claim": "roles",
                "value": "Analyst.Read",
                "role": "analyst",
                "domains": ["commercial:contoso:catalog:domain:finance"],
                "customer_control": False,
            },
            {
                "id": "finance-group",
                "claim": "groups",
                "value": GROUP.upper(),
                "role": "viewer",
                "domains": "all",
                "customer_control": False,
            },
        ],
    }
    parsed = parse_claim_role_mapping(json.dumps(raw))
    assert parsed is not None
    return parsed


def claims(**overrides: Any) -> VerifiedClaims:
    fields: dict[str, Any] = {
        "issuer_kind": "entra",
        "cloud": CloudName.COMMERCIAL,
        "issuer": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "audience": AUDIENCE,
        "tenant_id": TENANT,
        "object_id": OBJECT_ID,
        "subject": "subject-" + OBJECT_ID[:8],
        "token_version": "2.0",
        "issued_at": T0,
        "not_before": T0,
        "expires_at": T0 + timedelta(hours=1),
        "identity_type": "user",
        "scopes": ("access_as_user",),
        "roles": ("admin",),
    }
    fields.update(overrides)
    model = OverageClaims if "groups_overage" in fields else VerifiedClaims
    return model(**fields)


def ids(**overrides: Any) -> list[str]:
    allow_dev = overrides.pop("allow_dev_issuer", False)
    return [
        e.id for e in matching_entries(mapping(), claims(**overrides), allow_dev_issuer=allow_dev)
    ]


def test_mapped_role_value_matches() -> None:
    assert ids() == ["ns-admins"]


def test_unset_identity_type_with_scp_is_delegated() -> None:
    assert ids(identity_type=None) == ["ns-admins"]


def test_wrong_issuer_kind_never_matches() -> None:
    # VerifiedClaims only admits "entra" and "dev"; a model_construct stand-in shows any other
    # kind (for example a future "oidc") is refused by the closed constant.
    oidc = VerifiedClaims.model_construct(**{**claims().model_dump(), "issuer_kind": "oidc"})
    assert matching_entries(mapping(), oidc, allow_dev_issuer=True) == ()


def test_dev_issuer_refused_unless_allowed() -> None:
    dev = {"issuer_kind": "dev", "issuer": dev_issuer_for(TENANT)}
    assert ids(**dev) == []
    assert ids(**dev, allow_dev_issuer=True) == ["ns-admins"]


def test_dev_issuer_still_needs_tenant_and_audience() -> None:
    dev = {"issuer_kind": "dev", "allow_dev_issuer": True}
    assert ids(**dev, tenant_id=OTHER_TENANT) == []
    assert ids(**dev, audience="api://other") == []


def test_wrong_tenant() -> None:
    assert ids(tenant_id=OTHER_TENANT) == []


def test_wrong_audience() -> None:
    assert ids(audience="api://other-api") == []
    assert ids(audience=AUDIENCE.upper()) == []


def test_app_only_token() -> None:
    assert ids(identity_type="app") == []


def test_token_without_scp() -> None:
    assert ids(scopes=()) == []
    assert ids(scopes=(), identity_type=None) == []


def test_absent_roles_claim() -> None:
    assert ids(roles=()) == []


def test_unmapped_value() -> None:
    assert ids(roles=("reader", "Contributor")) == []


@pytest.mark.parametrize("value", ["Admin", "ADMIN", "analyst.read", " admin"])
def test_case_different_role_value_does_not_match(value: str) -> None:
    assert ids(roles=(value,)) == []


def test_group_matches_case_insensitively() -> None:
    assert ids(roles=(), groups=(GROUP,)) == ["finance-group"]
    assert ids(roles=(), groups=(GROUP.upper(),)) == ["finance-group"]


def test_unmapped_group() -> None:
    assert ids(roles=(), groups=(OTHER_GROUP,)) == []


def test_overage_blocks_group_entries_but_not_role_entries() -> None:
    assert ids(roles=(), groups=(GROUP,), groups_overage=True) == []
    assert ids(roles=("admin",), groups=(GROUP,), groups_overage=True) == ["ns-admins"]
    assert ids(roles=(), groups=(GROUP,), groups_overage=False) == ["finance-group"]


def test_union_of_several_matches_in_mapping_order() -> None:
    matched = ids(roles=("Analyst.Read", "admin", "admin"), groups=(OTHER_GROUP, GROUP))
    assert matched == ["ns-admins", "ns-analysts", "finance-group"]


def test_matching_returns_entry_objects() -> None:
    result = matching_entries(mapping(), claims(), allow_dev_issuer=False)
    assert isinstance(result, tuple)
    assert result == (mapping().entries[0],)
