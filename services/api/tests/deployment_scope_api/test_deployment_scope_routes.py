"""``require_deployment_admin`` (PRP-48 item 3, #114): one dependency for deployment-wide routes."""

from __future__ import annotations

from typing import Annotated, Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    CAROL,
    CUSTOMER,
    FINANCE,
    HR,
    NOBODY,
    OPERATIONS,
    OTHER_CUSTOMER_FINANCE,
    Harness,
    RecordingDenials,
    grant,
    harness,
    policy,
    role,
)
from fastapi import APIRouter, Depends
from neurosphere_api.actions import require_customer_control
from neurosphere_api.authz import (
    CUSTOMER_SCOPE_REQUIRED,
    DEPLOYMENT_ADMIN_MARKER,
    require_deployment_admin,
    route_inventory,
)
from neurosphere_api.authz.deployment_scope import (
    CUSTOMER_SCOPE_REQUIRED as MODULE_REASON,
)
from neurosphere_core.auth.scope import Permission, Role, customer_control_domain_id
from neurosphere_core.scope import IdentityScope

CONTROL = customer_control_domain_id("commercial", CUSTOMER)
OTHER_CONTROL = customer_control_domain_id("commercial", "fabrikam")
GOV_CONTROL = customer_control_domain_id("government", CUSTOMER)
DeploymentAdmin = Annotated[IdentityScope, Depends(require_deployment_admin())]
LifecycleAdmin = Annotated[
    IdentityScope, Depends(require_deployment_admin(Permission.LIFECYCLE_MANAGE))
]


def _router() -> APIRouter:
    router = APIRouter()

    @router.get("/settings")
    async def read_settings(scope: DeploymentAdmin) -> dict[str, Any]:
        return {"customer": scope.customer_id}

    @router.put("/settings")
    async def write_settings(scope: DeploymentAdmin) -> dict[str, Any]:
        return {"customer": scope.customer_id}

    @router.post("/lifecycle")
    async def lifecycle(scope: LifecycleAdmin) -> dict[str, Any]:
        return {"customer": scope.customer_id}

    return router


def _make(denials: RecordingDenials | None = None) -> Harness:
    return harness(
        # Deployment-scoped admin: config.manage on the control domain.
        policy(
            BOB,
            role(Role.ADMIN, FINANCE, CONTROL),
            memberships=(FINANCE, OPERATIONS, HR, CONTROL),
        ),
        # config.manage in ordinary domains only.
        policy(ALICE, role(Role.ADMIN, FINANCE, OPERATIONS)),
        # A steward on the control domain: membership but no config.manage there.
        policy(CAROL, role(Role.DOMAIN_STEWARD, FINANCE, CONTROL), memberships=(FINANCE, CONTROL)),
        # Another customer's / cloud's control domain, plus a grant naming ours.
        policy(
            NOBODY,
            role(Role.ADMIN, FINANCE, OTHER_CONTROL, GOV_CONTROL, OTHER_CUSTOMER_FINANCE),
            grants=(grant(CONTROL, "approve"),),
            memberships=(FINANCE, OTHER_CONTROL, GOV_CONTROL, OTHER_CUSTOMER_FINANCE),
        ),
        routers={"/t": _router()},
        denials=denials,
    )


def test_reason_code_is_the_shipped_customer_scope_code() -> None:
    assert CUSTOMER_SCOPE_REQUIRED == MODULE_REASON == "customer_scope_required"


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_deployment_scoped_admin_is_allowed(method: str) -> None:
    denials = RecordingDenials()
    h = _make(denials)
    response = h.client.request(method, "/t/settings", headers=h.auth(BOB))
    assert response.status_code == 200, response.text
    assert response.json() == {"customer": CUSTOMER}
    assert denials.attempts == []


@pytest.mark.parametrize("who", [ALICE, NOBODY], ids=["ordinary_domains", "foreign_control"])
def test_config_manage_elsewhere_is_403_and_recorded(who: str) -> None:
    denials = RecordingDenials()
    h = _make(denials)
    response = h.client.put("/t/settings", headers=h.auth(who))
    assert response.status_code == 403, response.text
    body = response.json()
    assert body["code"] == "forbidden"
    assert body["reason"] == CUSTOMER_SCOPE_REQUIRED
    assert len(denials.attempts) == 1
    attempt = denials.attempts[0]
    assert attempt.reason == CUSTOMER_SCOPE_REQUIRED
    assert attempt.permission == "config.manage"
    assert attempt.domain_id == CONTROL
    assert attempt.method == "PUT"


def test_membership_of_the_control_domain_without_the_permission_is_not_enough() -> None:
    denials = RecordingDenials()
    h = _make(denials)
    response = h.client.put("/t/settings", headers=h.auth(CAROL))
    assert response.status_code == 403
    assert response.json()["reason"] == "permission_missing"
    assert [a.reason for a in denials.attempts] == ["permission_missing"]


def test_other_permission_is_checked_on_the_control_domain() -> None:
    h = _make()
    # BOB is admin on the control domain, and admin holds lifecycle.manage.
    assert h.client.post("/t/lifecycle", headers=h.auth(BOB)).status_code == 200
    denied = h.client.post("/t/lifecycle", headers=h.auth(ALICE))
    assert denied.status_code == 403
    assert denied.json()["reason"] == CUSTOMER_SCOPE_REQUIRED


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_denial_audit_failure_fails_closed_on_every_method(method: str) -> None:
    h = _make(RecordingDenials(error=RuntimeError("audit down")))
    response = h.client.request(method, "/t/settings", headers=h.auth(ALICE))
    assert response.status_code == 503
    assert response.json()["reason"] == "audit_write_failed"


def test_unauthenticated_is_401() -> None:
    assert _make().client.put("/t/settings").status_code == 401


def test_route_inventory_still_sees_the_permission() -> None:
    h = _make()
    declared = {(e.path, e.methods): e.permissions for e in route_inventory(h.app)}
    assert declared[("/t/settings", ("PUT",))] == ("config.manage",)
    assert declared[("/t/lifecycle", ("POST",))] == ("lifecycle.manage",)


def test_require_customer_control_delegates() -> None:
    dep = require_customer_control(Permission.CONFIG_MANAGE)
    assert getattr(dep, DEPLOYMENT_ADMIN_MARKER, None) is Permission.CONFIG_MANAGE


def test_no_unrestricted_bypass_in_the_dependency_signature() -> None:
    """The dependency reads only the derived scope and the authz state; no flag, header or
    query parameter can switch the check off."""
    import inspect

    dep = require_deployment_admin()
    params = set(inspect.signature(dep).parameters)
    assert params == {"request", "scope", "state"}
