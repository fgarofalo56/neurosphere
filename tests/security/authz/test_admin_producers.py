"""ABAC negative suite for the producer admin routes (PRP-41 item 5).

The suite world (``world.py``) serves the real router table, so ``/api/v1/admin/sources/producers``
is mounted; this module installs the producer admin plane on each deployment (additive: the shared
harness files are not edited) and asserts that EVERY route refuses, per dimension, with a recorded
denial and no write:

=====================================  ====================================================
Dimension                              Expected refusal
=====================================  ====================================================
viewer / analyst / security auditor    403 ``permission_missing`` (no ``config.manage``)
``config.manage`` in an ordinary       403 ``customer_scope_required``
domain (domain admin)
expired customer-control admin         403 ``permission_missing``
wrong customer (create only)           403 ``cross_customer``, nothing stored
wrong cloud (create only)              422 ``cross_cloud``, nothing stored
=====================================  ====================================================
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from neurosphere_api.admin.sources.producers import ProducerAdminPlane, configure_producer_admin
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.admin.producers import ProducerAdmin
from neurosphere_core.auth.scope import (
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
    pseudonymizer,
)

BASE = "/api/v1/admin/sources/producers"
FIN = "finance"
VIEWER = Who("contoso", FIN, Role.VIEWER)
ANALYST = Who("contoso", FIN, Role.ANALYST)
AUDITOR = Who("contoso", FIN, Role.SECURITY_AUDITOR)
DOMAIN_ADMIN = Who("contoso", FIN, Role.ADMIN)
EXPIRED_ADMIN_OID = "a1b2c3d4-0000-4000-8000-00000000e041"
CONTOSO_CONTROL_OID = "a1b2c3d4-0000-4000-8000-00000000c041"
FABRIKAM_CONTROL_OID = "a1b2c3d4-0000-4000-8000-00000000c042"
CREATE: dict[str, Any] = {
    "producer_id": "poller-1",
    "cloud": "commercial",
    "sources": {"src-app": "application"},
}


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


def _seed_control_admin(dep: Deployment, object_id: str, *, expires_in: float) -> None:
    fin = domain_id(dep.customer, FIN)
    control = customer_control_domain_id("commercial", dep.customer)
    principal = pid_of(object_id, dep.customer)
    dep.repo.put_principal(
        PrincipalPolicy(
            id=principal_document_id(principal),
            customer_id=dep.customer,
            principal_id=principal,
            domain_memberships=(fin, control),
            role_assignments=(
                PolicyRoleAssignment(
                    assignment_id="ra-seeded",
                    role=Role.ADMIN,
                    domain_ids=(fin, control),
                    expires_at=at(expires_in),
                ),
            ),
        )
    )


def install(world: World) -> dict[str, InMemoryAdminConfigRepository]:
    repos: dict[str, InMemoryAdminConfigRepository] = {}
    for customer, dep in world.deployments.items():
        repo = InMemoryAdminConfigRepository(cloud="commercial")
        repos[customer] = repo
        configure_producer_admin(
            dep.app,
            ProducerAdminPlane(admin=ProducerAdmin(repo, cloud="commercial"), audit=dep.audit_repo),
        )
    _seed_control_admin(world["contoso"], CONTOSO_CONTROL_OID, expires_in=7 * 24 * 3600)
    _seed_control_admin(world["contoso"], EXPIRED_ADMIN_OID, expires_in=10)
    _seed_control_admin(world["fabrikam"], FABRIKAM_CONTROL_OID, expires_in=7 * 24 * 3600)
    return repos


@dataclass(frozen=True)
class Route:
    name: str
    method: str
    path: str
    body: dict[str, Any] | None


IF_MATCH = {"If-Match": '"cfg-1"'}
ROUTES: tuple[Route, ...] = (
    Route("create", "POST", BASE, CREATE),
    Route("list", "GET", BASE, None),
    Route("detail", "GET", f"{BASE}/poller-1", None),
    Route("rotate", "POST", f"{BASE}/poller-1/rotate", None),
    Route("disable", "POST", f"{BASE}/poller-1/disable", None),
    Route("enable", "POST", f"{BASE}/poller-1/enable", None),
)


@pytest.fixture
def pworld(world: World) -> World:
    world.repos = install(world)  # type: ignore[attr-defined]
    return world


def repo_of(world: World, customer: str = "contoso") -> InMemoryAdminConfigRepository:
    return world.repos[customer]  # type: ignore[attr-defined,no-any-return]


def stored(world: World, customer: str = "contoso") -> int:
    return len(repo_of(world, customer)._docs)  # pyright: ignore[reportPrivateUsage]


def denial_reasons(dep: Deployment) -> list[str]:
    return [a.reason for a in dep.recorder.attempts]


def call(dep: Deployment, route: Route, headers: dict[str, str]) -> Any:
    return dep.client.request(
        route.method, route.path, headers={**IF_MATCH, **headers}, json=route.body
    )


def test_every_route_in_the_inventory_has_a_case() -> None:
    from fastapi.routing import APIRoute
    from neurosphere_api.admin.sources.producers import build_router

    served = {
        (BASE + (r.path if r.path != "/" else ""), m)
        for r in build_router().routes
        if isinstance(r, APIRoute)
        for m in sorted(r.methods or ())
    }
    cases = {(r.path.replace("poller-1", "{producer_id}"), r.method) for r in ROUTES}
    assert served == cases


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
@pytest.mark.parametrize("who", [VIEWER, ANALYST, AUDITOR], ids=lambda w: w.role.value)
def test_roles_without_config_manage(pworld: World, route: Route, who: Who) -> None:
    dep = pworld["contoso"]
    response = call(dep, route, dep.bearer(who))
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "permission_missing"
    assert "permission_missing" in denial_reasons(dep)
    assert stored(pworld) == 0


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_ordinary_domain_admin_needs_customer_scope(pworld: World, route: Route) -> None:
    dep = pworld["contoso"]
    response = call(dep, route, dep.bearer(DOMAIN_ADMIN))
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "customer_scope_required"
    assert "customer_scope_required" in denial_reasons(dep)
    assert stored(pworld) == 0


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_expired_customer_control_admin(pworld: World, route: Route) -> None:
    dep = pworld["contoso"]
    pworld.clock.advance(11)  # the seeded assignment lapsed
    response = call(dep, route, bearer_for(dep, EXPIRED_ADMIN_OID))
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "permission_missing"
    assert "permission_missing" in denial_reasons(dep)
    assert stored(pworld) == 0


def test_wrong_customer_is_refused_and_nothing_is_stored(pworld: World) -> None:
    fab = pworld["fabrikam"]
    body = {**CREATE, "customer_id": "contoso"}
    response = fab.client.post(BASE, headers=bearer_for(fab, FABRIKAM_CONTROL_OID), json=body)
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "cross_customer"
    assert stored(pworld, "fabrikam") == 0 and stored(pworld, "contoso") == 0


def test_wrong_cloud_is_refused_and_nothing_is_stored(pworld: World) -> None:
    dep = pworld["contoso"]
    body = {**CREATE, "cloud": "government"}
    response = dep.client.post(BASE, headers=bearer_for(dep, CONTOSO_CONTROL_OID), json=body)
    assert response.status_code == 422, response.text
    assert response.json()["reason"] == "cross_cloud"
    assert stored(pworld) == 0


def test_customer_admin_of_another_customer_cannot_read_ours(pworld: World) -> None:
    dep = pworld["contoso"]
    created = dep.client.post(BASE, headers=bearer_for(dep, CONTOSO_CONTROL_OID), json=CREATE)
    assert created.status_code == 201, created.text
    fab = pworld["fabrikam"]
    other = fab.client.get(f"{BASE}/poller-1", headers=bearer_for(fab, FABRIKAM_CONTROL_OID))
    assert other.status_code == 404
    listing = fab.client.get(BASE, headers=bearer_for(fab, FABRIKAM_CONTROL_OID))
    assert listing.json()["items"] == []
