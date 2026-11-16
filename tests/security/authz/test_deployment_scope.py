"""ABAC negative suite for deployment-scoped administration (PRP-48 item 3, #114).

MCP server administration, deploy scan and plan, and the execution kill switch change state that
applies to the whole deployment. ``config.manage`` in an ordinary domain is never enough: each
route needs the deployment-scoped admin (``config.manage`` on the customer's reserved control
domain, ``require_deployment_admin``). The suite world serves the real router table; no plane is
installed, so an authorized call reaches the route and fails later (503 unconfigured), while a
refused one stops at the authorization dependency with a recorded denial.

=====================================  ====================================================
Dimension                              Expected refusal
=====================================  ====================================================
viewer / analyst / security auditor    403 ``permission_missing`` (no ``config.manage``)
``config.manage`` in an ordinary       403 ``customer_scope_required``, denial recorded on
domain (domain admin)                  the control domain target
control-domain admin of ANOTHER        403 ``customer_scope_required`` (derivation clips
customer                               the foreign control domain)
expired control-domain admin           403 ``permission_missing``
resource grant naming the control      403 (a grant never confers customer-wide authority)
domain id
=====================================  ====================================================
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from neurosphere_api.authz.deployment_scope import (
    CUSTOMER_SCOPE_REQUIRED,
    DEPLOYMENT_ADMIN_MARKER,
)
from neurosphere_core.auth.scope import (
    Permission,
    PolicyRoleAssignment,
    PrincipalPolicy,
    Role,
    customer_control_domain_id,
    principal_document_id,
)
from neurosphere_core.cloud import CloudName

from .world import (
    AUDIENCE,
    TENANTS,
    Deployment,
    Who,
    World,
    at,
    dev_issuer,
    domain_id,
    make_grant,
    pseudonymizer,
)

FIN = "finance"
VIEWER = Who("contoso", FIN, Role.VIEWER)
ANALYST = Who("contoso", FIN, Role.ANALYST)
AUDITOR = Who("contoso", FIN, Role.SECURITY_AUDITOR)
DOMAIN_ADMIN = Who("contoso", FIN, Role.ADMIN)
CONTROL_OID = "a1b2c3d4-0000-4000-8000-00000000c048"
EXPIRED_OID = "a1b2c3d4-0000-4000-8000-00000000e048"
FOREIGN_CONTROL_OID = "a1b2c3d4-0000-4000-8000-00000000f048"
GRANT_OID = "a1b2c3d4-0000-4000-8000-00000000a048"
CONTROL = customer_control_domain_id("commercial", "contoso")
FABRIKAM_CONTROL = customer_control_domain_id("commercial", "fabrikam")
SERVER = "mcp-" + "0" * 32


@dataclass(frozen=True)
class Route:
    name: str
    method: str
    path: str
    body: dict[str, Any] | None = None


#: The four route groups #114 names. MCP admin: every route of the router.
ROUTES: tuple[Route, ...] = (
    Route(
        "mcp.register",
        "POST",
        "/api/v1/mcp/admin/servers",
        {"url": "https://mcp.example.com/mcp", "display_name": "Example"},
    ),
    Route("mcp.list", "GET", "/api/v1/mcp/admin/servers"),
    Route("mcp.detail", "GET", f"/api/v1/mcp/admin/servers/{SERVER}"),
    Route("mcp.sync", "POST", f"/api/v1/mcp/admin/servers/{SERVER}/sync"),
    Route("mcp.tools", "GET", f"/api/v1/mcp/admin/servers/{SERVER}/tools"),
    Route("deploy.scan", "POST", "/api/v1/deploy/scan", {}),
    Route("deploy.plan", "POST", "/api/v1/deploy/plan", {}),
    Route(
        "actions.kill_switch",
        "PUT",
        "/api/v1/actions/emergency-disable",
        {"disabled": True, "reason": "incident_inc_48"},
    ),
)


def pid_of(object_id: str, customer: str) -> str:
    return pseudonymizer().principal_id(
        cloud=CloudName.COMMERCIAL,
        customer_id=customer,
        tenant_id=TENANTS[customer],
        object_id=object_id,
        kind="user",
    )


def bearer_for(dep: Deployment, object_id: str) -> dict[str, str]:
    token = dev_issuer(dep.customer).mint(audience=AUDIENCE, object_id=object_id, now=dep.clock.now)
    return {"Authorization": f"Bearer {token}"}


def _seed(
    dep: Deployment,
    object_id: str,
    *,
    domains: tuple[str, ...],
    expires_in: float = 7 * 24 * 3600,
    grants: tuple[Any, ...] = (),
) -> None:
    principal = pid_of(object_id, dep.customer)
    dep.repo.put_principal(
        PrincipalPolicy(
            id=principal_document_id(principal),
            customer_id=dep.customer,
            principal_id=principal,
            domain_memberships=domains,
            role_assignments=(
                PolicyRoleAssignment(
                    assignment_id="ra-prp48",
                    role=Role.ADMIN,
                    domain_ids=domains,
                    expires_at=at(expires_in),
                ),
            ),
            grants=grants,
        )
    )


@pytest.fixture
def dworld(world: World) -> World:
    dep = world["contoso"]
    fin = domain_id("contoso", FIN)
    _seed(dep, CONTROL_OID, domains=(fin, CONTROL))
    _seed(dep, EXPIRED_OID, domains=(fin, CONTROL), expires_in=10)
    # A contoso principal whose policy names fabrikam's control domain: derivation clips it.
    _seed(dep, FOREIGN_CONTROL_OID, domains=(fin, FABRIKAM_CONTROL))
    # config.manage in finance plus a resource grant whose target is the control domain id.
    _seed(
        dep,
        GRANT_OID,
        domains=(fin,),
        grants=(make_grant(CONTROL, "approve", grant_id="g-control"),),
    )
    return world


def call(dep: Deployment, route: Route, headers: dict[str, str]) -> Any:
    return dep.client.request(route.method, route.path, headers=headers, json=route.body)


def reasons(dep: Deployment) -> list[str]:
    return [a.reason for a in dep.recorder.attempts]


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
@pytest.mark.parametrize("who", [VIEWER, ANALYST, AUDITOR], ids=lambda w: w.role.value)
def test_roles_without_config_manage(dworld: World, route: Route, who: Who) -> None:
    dep = dworld["contoso"]
    response = call(dep, route, dep.bearer(who))
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "permission_missing"
    assert reasons(dep) == ["permission_missing"]


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_ordinary_domain_admin_needs_deployment_scope(dworld: World, route: Route) -> None:
    dep = dworld["contoso"]
    response = call(dep, route, dep.bearer(DOMAIN_ADMIN))
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == CUSTOMER_SCOPE_REQUIRED
    assert reasons(dep) == [CUSTOMER_SCOPE_REQUIRED]
    attempt = dep.recorder.attempts[0]
    assert attempt.permission == Permission.CONFIG_MANAGE.value
    assert attempt.domain_id == CONTROL  # the target is the deployment, never caller input


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_foreign_control_domain_never_authorizes(dworld: World, route: Route) -> None:
    dep = dworld["contoso"]
    response = call(dep, route, bearer_for(dep, FOREIGN_CONTROL_OID))
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == CUSTOMER_SCOPE_REQUIRED


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_resource_grant_on_the_control_domain_is_not_deployment_scope(
    dworld: World, route: Route
) -> None:
    dep = dworld["contoso"]
    response = call(dep, route, bearer_for(dep, GRANT_OID))
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == CUSTOMER_SCOPE_REQUIRED


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_expired_control_admin(dworld: World, route: Route) -> None:
    dep = dworld["contoso"]
    dworld.clock.advance(11)
    response = call(dep, route, bearer_for(dep, EXPIRED_OID))
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "permission_missing"


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_deployment_scoped_admin_passes_authorization(dworld: World, route: Route) -> None:
    """Positive control: no 401/403 and no denial; the unconfigured plane answers instead."""
    dep = dworld["contoso"]
    response = call(dep, route, bearer_for(dep, CONTROL_OID))
    assert response.status_code not in (401, 403), response.text
    assert reasons(dep) == []


def test_every_route_of_the_four_groups_is_deployment_scoped(world: World) -> None:
    """Structural: each route of the four groups carries the deployment-scope dependency."""
    from fastapi.routing import iter_route_contexts
    from starlette.routing import BaseRoute

    def marked(dependant: Any) -> bool:
        if getattr(dependant.call, DEPLOYMENT_ADMIN_MARKER, None) is Permission.CONFIG_MANAGE:
            return True
        return any(marked(child) for child in dependant.dependencies)

    app = world["contoso"].app
    prefixes = ("/api/v1/mcp/admin/", "/api/v1/deploy/scan", "/api/v1/deploy/plan")
    checked: set[tuple[str, str]] = set()
    for context in iter_route_contexts(app.routes):
        effective = getattr(context, "starlette_route", None)
        source: Any = effective if isinstance(effective, BaseRoute) else context
        path = getattr(source, "path", "")
        methods = set(getattr(source, "methods", None) or ())
        dependant = getattr(source, "dependant", None)
        in_group = path.startswith(prefixes) or (
            path == "/api/v1/actions/emergency-disable" and "PUT" in methods
        )
        if in_group and dependant is not None:
            assert marked(dependant), path
            checked.update((path, m) for m in methods)
    assert ("/api/v1/mcp/admin/servers", "POST") in checked
    assert ("/api/v1/deploy/scan", "POST") in checked
    assert ("/api/v1/deploy/plan", "POST") in checked
    assert ("/api/v1/actions/emergency-disable", "PUT") in checked
