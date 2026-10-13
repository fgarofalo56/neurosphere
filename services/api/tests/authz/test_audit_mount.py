"""Item 4's audit router mounted behind ``require`` via ``audit_require_permission``."""

from __future__ import annotations

import pytest
from neurosphere_api.audit import ROUTE_PREFIX, build_router, register
from neurosphere_api.authz import (
    audit_require_permission,
    domain_from_chain_id,
    route_inventory,
    undeclared_routes,
)
from neurosphere_api.routers import RouterRegistry
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope import Role
from neurosphere_core.errors import InvalidSchemaError

from .authz_helpers import ALICE, CAROL, FINANCE, Harness, harness, policy, role

POLICIES = (
    policy(ALICE, role(Role.VIEWER, FINANCE)),
    policy(CAROL, role(Role.SECURITY_AUDITOR, FINANCE)),
)


def _audit_harness() -> Harness:
    factory = audit_require_permission(chain_domain=domain_from_chain_id)
    h = harness(*POLICIES, routers={ROUTE_PREFIX: build_router(require_permission=factory)})
    h.app.state.audit_repository = AuditRepository(InMemoryAuditStore())
    return h


# (principal, chain, endpoint, status, reason)
CASES: list[tuple[str | None, str, str, int, str | None]] = [
    (None, "contoso.finance", "records", 401, "missing_token"),
    (CAROL, "contoso.finance", "records", 200, None),
    (CAROL, "contoso.finance", "verify", 200, None),
    (CAROL, "contoso.hr", "records", 403, "target_out_of_scope"),  # no customer-level fallback
    (CAROL, "fabrikam.finance", "verify", 403, "audit_chain_out_of_scope"),
    (CAROL, "contosox.finance", "verify", 403, "audit_chain_out_of_scope"),
    (CAROL, "contoso", "records", 403, "audit_chain_out_of_scope"),
    (CAROL, "contoso.", "records", 403, "audit_chain_out_of_scope"),
    (CAROL, "contoso.Not_A_Domain", "records", 403, "target_unresolved"),  # off-convention: deny
    (ALICE, "contoso.finance", "records", 403, "target_out_of_scope"),
]


@pytest.mark.parametrize(("who", "chain", "endpoint", "status", "reason"), CASES)
def test_audit_routes_behind_require(
    who: str | None, chain: str, endpoint: str, status: int, reason: str | None
) -> None:
    h = _audit_harness()
    headers = h.auth(who) if who else {}
    response = h.client.get(f"{ROUTE_PREFIX}/chains/{chain}/{endpoint}", headers=headers)
    assert response.status_code == status, response.text
    if reason is not None:
        assert response.json()["reason"] == reason


def test_audit_routes_declare_permissions() -> None:
    h = _audit_harness()
    assert undeclared_routes(h.app) == ()
    audit = [e for e in route_inventory(h.app) if e.path.startswith(ROUTE_PREFIX)]
    assert len(audit) == 2
    assert all(e.permissions == ("audit.read",) for e in audit)


def test_register_hook_accepts_the_adapter() -> None:
    registry = RouterRegistry()
    register(
        registry, require_permission=audit_require_permission(chain_domain=domain_from_chain_id)
    )
    assert registry.prefixes == (ROUTE_PREFIX,)


def test_unknown_audit_permission_fails_at_mount() -> None:
    with pytest.raises(InvalidSchemaError):
        audit_require_permission(chain_domain=domain_from_chain_id)("audit.write")


def test_a_domain_mapper_is_mandatory() -> None:
    with pytest.raises(TypeError):
        audit_require_permission()  # type: ignore[call-arg]


@pytest.mark.parametrize("endpoint", ["records", "verify"])
def test_default_app_mounts_audit_and_fails_closed_until_configured(endpoint: str) -> None:
    from fastapi.testclient import TestClient
    from neurosphere_api.app import create_app
    from neurosphere_core.cloud import Settings

    client = TestClient(create_app(Settings(env="local")), raise_server_exceptions=False)
    for headers in ({}, {"Authorization": "Bearer not-a-token"}):
        response = client.get(f"{ROUTE_PREFIX}/chains/contoso.hr/{endpoint}", headers=headers)
        assert response.status_code == 503
