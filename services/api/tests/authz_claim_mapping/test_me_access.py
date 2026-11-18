"""PRP-138 item 5: ``GET /api/v1/me/access``, the caller's own roles and where they came from.

The app is the factory app with every default router, authorized by a real ``ScopeDeriver`` over
an in-memory policy store, with the claim role mapping applied to dev-issuer tokens (the local
issuer is accepted for mapping only when the deriver allows it, as in ``NS_ENV=local``). No
network, no cloud.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    AUDIENCE,
    BOB,
    CUSTOMER,
    FINANCE,
    HR,
    NOBODY,
    OPERATIONS,
    POLICY_VERSION,
    TENANT,
    FakeClock,
    dev_issuer,
    make_app,
    make_validator,
    policy,
    pseudonymizer,
    role,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from neurosphere_api.admin.identity.role_mapping import CLAIM_ROLE_MAPPING_ATTRIBUTE
from neurosphere_api.authz import ClaimMappingStats, configure_authz
from neurosphere_api.authz.claim_audit import install_claim_mapping_stats
from neurosphere_api.runtime.builders import CLAIM_ROLE_MAPPING
from neurosphere_core.auth.scope import (
    ClaimRoleMapping,
    InMemoryPolicyRepository,
    NoRevocationCheck,
    PolicyHead,
    PrincipalPolicy,
    Role,
    ScopeDerivationConfig,
    ScopeDeriver,
    customer_control_domain_id,
    parse_claim_role_mapping,
)
from neurosphere_core.cloud import CloudName

ACCESS = "/api/v1/me/access"
CONTROL = customer_control_domain_id("commercial", CUSTOMER)
ADMIN_VALUE = "NeuroSphere.Admin"
VIEWER_VALUE = "Ops.Viewer"
GROUP = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
LIFETIME = 3600
SCOPES = ("access_as_user",)
GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

MAPPING_DOC: dict[str, Any] = {
    "tenant_id": TENANT,
    "audience": AUDIENCE,
    "entries": [
        {
            "id": "ns-admins",
            "claim": "roles",
            "value": ADMIN_VALUE,
            "role": "admin",
            "domains": "all",
            "customer_control": True,
        },
        {
            "id": "finance-analysts",
            "claim": "groups",
            "value": GROUP,
            "role": "analyst",
            "domains": [FINANCE],
            "customer_control": False,
        },
        {
            "id": "ops-viewers",
            "claim": "roles",
            "value": VIEWER_VALUE,
            "role": "viewer",
            "domains": [OPERATIONS],
            "customer_control": False,
        },
    ],
}


def the_mapping() -> ClaimRoleMapping:
    mapping = parse_claim_role_mapping(json.dumps(MAPPING_DOC))
    assert mapping is not None
    return mapping


class StaticDirectory:
    """The domain registry's active domains (the deriver expands ``all`` from it)."""

    async def active_domain_ids(self, customer_id: str) -> tuple[str, ...]:
        assert customer_id == CUSTOMER
        return (FINANCE, OPERATIONS, HR)


@dataclass
class MappedHarness:
    app: FastAPI
    client: TestClient
    clock: FakeClock

    def token(self, object_id: str, *, roles: tuple[str, ...] = (), **extra: Any) -> dict[str, str]:
        token = dev_issuer().mint(
            audience=AUDIENCE,
            object_id=object_id,
            now=self.clock.now,
            lifetime_seconds=LIFETIME,
            roles=roles,
            scopes=SCOPES,
            extra=extra or None,
        )
        return {"Authorization": f"Bearer {token}"}

    def token_expiry(self) -> datetime:
        return datetime.fromtimestamp(int(self.clock.now) + LIFETIME, UTC)


def mapped_harness(
    *policies: PrincipalPolicy,
    mapping: ClaimRoleMapping | None = None,
    install: str = "mapping",
) -> MappedHarness:
    """App with the mapping applied by the deriver.

    ``install`` says how the composition exposes it on ``app.state``: ``mapping`` (the parsed
    mapping, as the role-mapping view reads it), ``stats`` (the claim mapping counters only), or
    ``none``.
    """
    clock = FakeClock()
    repo = InMemoryPolicyRepository()
    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version=POLICY_VERSION))
    for p in policies:
        repo.put_principal(p)
    config = ScopeDerivationConfig(
        cloud=CloudName.COMMERCIAL, tenant_id=TENANT, customer_id=CUSTOMER
    )
    options: dict[str, Any] = {}
    if mapping is not None:
        options = {
            "claim_mapping": mapping,
            "domain_directory": StaticDirectory(),
            "allow_dev_issuer": True,
        }
    deriver = ScopeDeriver(
        config,
        policy_repository=repo,
        pseudonymizer=pseudonymizer(),
        revocation_checker=NoRevocationCheck(),
        clock=clock,
        **options,
    )
    app = make_app(routers={})
    configure_authz(app, authenticator=make_validator(clock), scope_source=deriver, clock=clock)
    if mapping is not None and install == "mapping":
        setattr(app.state, CLAIM_ROLE_MAPPING_ATTRIBUTE, mapping)
    if mapping is not None and install in ("mapping", "stats"):
        install_claim_mapping_stats(app.state, ClaimMappingStats(mapping))
    return MappedHarness(
        app=app, client=TestClient(app, raise_server_exceptions=False), clock=clock
    )


def _get(h: MappedHarness, headers: dict[str, str]) -> dict[str, Any]:
    response = h.client.get(ACCESS, headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _rows(body: dict[str, Any]) -> set[tuple[Any, ...]]:
    return {
        (r["role"], r["source"], r["mapping_entry_id"], r["domain_count"], r["customer_control"])
        for r in body["roles"]
    }


# --------------------------------------------------------------------------- basics


def test_the_state_attribute_is_the_shared_key_name() -> None:
    assert CLAIM_ROLE_MAPPING_ATTRIBUTE == CLAIM_ROLE_MAPPING.name


def test_unauthenticated_caller_gets_401() -> None:
    h = mapped_harness(mapping=the_mapping())
    assert h.client.get(ACCESS).status_code == 401
    assert h.client.get(ACCESS, headers={"Authorization": "Bearer nope"}).status_code == 401


def test_roleless_caller_gets_200_with_an_empty_list() -> None:
    h = mapped_harness(mapping=the_mapping())
    body = _get(h, h.token(NOBODY))
    assert body == {"mapping_configured": True, "groups_overage": False, "roles": []}


def test_mapping_not_configured() -> None:
    h = mapped_harness(policy(ALICE, role(Role.VIEWER, FINANCE)))
    body = _get(h, h.token(ALICE, roles=(ADMIN_VALUE,)))  # the claim is ignored without a mapping
    assert body["mapping_configured"] is False
    assert _rows(body) == {("viewer", "policy_store", None, 1, False)}


def test_mapping_configured_is_seen_from_the_counters_alone() -> None:
    """The composed authz builder installs the counters whenever a mapping is configured."""
    h = mapped_harness(mapping=the_mapping(), install="stats")
    assert _get(h, h.token(NOBODY))["mapping_configured"] is True


def test_only_get_is_served() -> None:
    h = mapped_harness(mapping=the_mapping())
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert h.client.request(method, ACCESS, headers=h.token(NOBODY)).status_code == 405


# --------------------------------------------------------------------------- sources


def test_stored_roles_only() -> None:
    h = mapped_harness(
        policy(ALICE, role(Role.VIEWER, FINANCE), role(Role.ANALYST, FINANCE, OPERATIONS)),
        mapping=the_mapping(),
    )
    body = _get(h, h.token(ALICE))
    assert _rows(body) == {
        ("viewer", "policy_store", None, 1, False),
        ("analyst", "policy_store", None, 2, False),
    }
    assert all(r["expires_at"] is None for r in body["roles"])


def test_mapped_app_role() -> None:
    h = mapped_harness(mapping=the_mapping())
    body = _get(h, h.token(BOB, roles=(ADMIN_VALUE,)))
    [row] = body["roles"]
    assert row == {
        "role": "admin",
        "source": "entra_app_role",
        "mapping_entry_id": "ns-admins",
        "domain_count": 4,  # every registry domain plus the control domain
        "customer_control": True,
        "expires_at": row["expires_at"],
    }
    expires = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
    assert expires == h.token_expiry()
    assert row["expires_at"].endswith("Z")


def test_mapped_group_role() -> None:
    h = mapped_harness(mapping=the_mapping())
    body = _get(h, h.token(BOB, groups=[GROUP]))
    assert _rows(body) == {("analyst", "entra_group", "finance-analysts", 1, False)}
    assert body["groups_overage"] is False


def test_stored_and_mapped_same_role_are_told_apart() -> None:
    """A stored analyst on FINANCE and a group-mapped analyst on FINANCE: two rows, by grants."""
    h = mapped_harness(policy(ALICE, role(Role.ANALYST, FINANCE)), mapping=the_mapping())
    body = _get(h, h.token(ALICE, groups=[GROUP]))
    assert sorted(_rows(body)) == sorted(
        {
            ("analyst", "policy_store", None, 1, False),
            ("analyst", "entra_group", "finance-analysts", 1, False),
        }
    )
    by_source = {r["source"]: r for r in body["roles"]}
    assert by_source["policy_store"]["expires_at"] is None
    assert by_source["entra_group"]["expires_at"] is not None


def test_stored_and_mapped_admin_with_expiries_are_told_apart() -> None:
    """Both privileged and time-bound: the grant's domains and expiry pick the mapped one."""
    h = mapped_harness(
        policy(ALICE, role(Role.ADMIN, CONTROL), memberships=(FINANCE, CONTROL)),
        mapping=the_mapping(),
    )
    body = _get(h, h.token(ALICE, roles=(ADMIN_VALUE, VIEWER_VALUE)))
    assert sorted(_rows(body)) == sorted(
        {
            ("admin", "policy_store", None, 1, True),
            ("admin", "entra_app_role", "ns-admins", 4, True),
            ("viewer", "entra_app_role", "ops-viewers", 1, False),
        }
    )
    assert all(r["expires_at"] is not None for r in body["roles"])


def test_customer_control_flag_follows_the_domains() -> None:
    h = mapped_harness(
        policy(
            ALICE,
            role(Role.ADMIN, CONTROL),
            role(Role.VIEWER, FINANCE),
            memberships=(FINANCE, CONTROL),
        ),
    )
    flags = {r["role"]: r["customer_control"] for r in _get(h, h.token(ALICE))["roles"]}
    assert flags == {"admin": True, "viewer": False}


def test_groups_overage_is_reported_and_no_group_role_is_applied() -> None:
    h = mapped_harness(mapping=the_mapping())
    body = _get(h, h.token(BOB, roles=(VIEWER_VALUE,), groups=[GROUP], hasgroups=True))
    assert body["groups_overage"] is True
    assert _rows(body) == {("viewer", "entra_app_role", "ops-viewers", 1, False)}


def test_response_carries_no_domain_id_guid_or_claim_value() -> None:
    h = mapped_harness(
        policy(
            ALICE,
            role(Role.ANALYST, FINANCE),
            role(Role.ADMIN, CONTROL),
            memberships=(FINANCE, CONTROL),
        ),
        mapping=the_mapping(),
    )
    response = h.client.get(ACCESS, headers=h.token(ALICE, roles=(ADMIN_VALUE,), groups=[GROUP]))
    assert response.status_code == 200
    text = response.text
    assert len(response.json()["roles"]) == 4
    for forbidden in (ADMIN_VALUE, VIEWER_VALUE, GROUP, TENANT, AUDIENCE, ALICE, CUSTOMER):
        assert forbidden not in text
    assert ":domain:" not in text
    assert GUID.search(text) is None
    assert "principal" not in text
    assert set(response.json()) == {"mapping_configured", "groups_overage", "roles"}
