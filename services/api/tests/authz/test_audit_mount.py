"""Item 4's audit router mounted behind ``require`` via ``audit_require_permission``."""

from __future__ import annotations

import pytest
from neurosphere_api.audit import ROUTE_PREFIX, build_router, register
from neurosphere_api.authz import audit_require_permission, route_inventory, undeclared_routes
from neurosphere_api.routers import RouterRegistry
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope import Role
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.scope import IdentityScope

from .authz_helpers import ALICE, CAROL, FINANCE, Harness, harness, policy, role

POLICIES = (
    policy(ALICE, role(Role.VIEWER, FINANCE)),
    policy(CAROL, role(Role.SECURITY_AUDITOR, FINANCE)),
)


def _domain_of_chain(scope: IdentityScope, chain_id: str) -> str | None:
    name = chain_id.partition(".")[2]
    return f"{scope.cloud}:{scope.customer_id}:catalog:domain:{name}" if name else None


def _audit_harness(*, mapped: bool) -> Harness:
    factory = audit_require_permission(chain_domain=_domain_of_chain if mapped else None)
    h = harness(*POLICIES, routers={ROUTE_PREFIX: build_router(require_permission=factory)})
    h.app.state.audit_repository = AuditRepository(InMemoryAuditStore())
    return h


# (mapped, principal, chain, endpoint, status, reason)
CASES: list[tuple[bool, str | None, str, str, int, str | None]] = [
    (False, None, "contoso.finance", "records", 401, "missing_token"),
    (False, CAROL, "contoso.finance", "records", 200, None),
    (False, CAROL, "contoso.finance", "verify", 200, None),
    (False, CAROL, "contoso.hr", "records", 200, None),  # customer-level confinement only
    (False, CAROL, "fabrikam.finance", "records", 403, "audit_chain_out_of_scope"),
    (False, CAROL, "contosox.finance", "verify", 403, "audit_chain_out_of_scope"),
    (False, CAROL, "contoso", "records", 403, "audit_chain_out_of_scope"),
    (False, ALICE, "contoso.finance", "records", 403, "permission_missing"),
    (True, CAROL, "contoso.finance", "records", 200, None),
    (True, CAROL, "contoso.hr", "records", 403, "target_out_of_scope"),
    (True, CAROL, "fabrikam.finance", "verify", 403, "audit_chain_out_of_scope"),
    (True, CAROL, "contoso", "records", 403, "audit_chain_out_of_scope"),
    (True, CAROL, "contoso.", "records", 403, "audit_chain_out_of_scope"),
    (True, ALICE, "contoso.finance", "records", 403, "target_out_of_scope"),
]


@pytest.mark.parametrize(("mapped", "who", "chain", "endpoint", "status", "reason"), CASES)
def test_audit_routes_behind_require(
    mapped: bool, who: str | None, chain: str, endpoint: str, status: int, reason: str | None
) -> None:
    h = _audit_harness(mapped=mapped)
    headers = h.auth(who) if who else {}
    response = h.client.get(f"{ROUTE_PREFIX}/chains/{chain}/{endpoint}", headers=headers)
    assert response.status_code == status, response.text
    if reason is not None:
        assert response.json()["reason"] == reason


def test_audit_routes_declare_permissions() -> None:
    h = _audit_harness(mapped=False)
    assert undeclared_routes(h.app) == ()
    audit = [e for e in route_inventory(h.app) if e.path.startswith(ROUTE_PREFIX)]
    assert len(audit) == 2
    assert all(e.permissions == ("audit.read",) for e in audit)


def test_register_hook_accepts_the_adapter() -> None:
    registry = RouterRegistry()
    register(registry, require_permission=audit_require_permission())
    assert registry.prefixes == (ROUTE_PREFIX,)


def test_unknown_audit_permission_fails_at_mount() -> None:
    with pytest.raises(InvalidSchemaError):
        audit_require_permission()("audit.write")
