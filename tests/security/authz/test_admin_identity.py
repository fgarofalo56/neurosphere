"""ABAC negative suite for the identity admin POLICY routes (PRP-39 item 5).

The suite world (``world.py``) already serves the real application router table, so the
``/api/v1/admin/identity`` routes are mounted; this module installs the identity admin plane on
each deployment (additive: the shared harness files are not edited) and asserts that every new
route refuses, per dimension, with a recorded denial and no write:

=================================  ==========================================================
Dimension                          Expected refusal
=================================  ==========================================================
cross-customer target              403 ``cross_scope_target``
cross-cloud target                 403 ``cross_scope_target``
cross-domain change                403 ``target_out_of_scope`` (domain the actor does not manage)
self-grant                         403 ``self_modification_forbidden``
privileged without customer scope  403 ``customer_scope_required`` (role routes); grants and
                                   memberships have no privileged form, so their privileged
                                   case is the customer-control domain or an unmanaged owner
expired assignment                 403 ``permission_missing``
revoked actor                      403 ``principal_revoked``
=================================  ==========================================================
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from neurosphere_api.admin.identity import IdentityAdminPlane, configure_identity_admin
from neurosphere_core.auth.scope import (
    PolicyRoleAssignment,
    PrincipalPolicy,
    Role,
    customer_control_domain_id,
    principal_document_id,
)
from neurosphere_core.auth.scope.policy_admin import InMemoryPolicyAdminRepository
from neurosphere_core.cloud import CloudName
from neurosphere_core.scope import IdentityScope

from .world import (
    AUDIENCE,
    TENANTS,
    Deployment,
    Who,
    World,
    at,
    dev_issuer,
    domain_id,
    item_id,
    pseudonymizer,
    run,
)

BASE = "/api/v1/admin/identity/principals"
FIN = "finance"
OPS = "operations"
ADMIN = Who("contoso", FIN, Role.ADMIN)
ANALYST = Who("contoso", FIN, Role.ANALYST)
OPS_ANALYST = Who("contoso", OPS, Role.ANALYST)
FABRIKAM_ANALYST = Who("fabrikam", FIN, Role.ANALYST)
FIN_AGENT = item_id("contoso", FIN, 1)
OPS_AGENT = item_id("contoso", OPS, 1)
#: Extra contoso principals this module seeds (object ids are fixtures, never asserted on output).
EXPIRED_ADMIN_OID = "a1b2c3d4-0000-4000-8000-00000000e001"
CUSTOMER_ADMIN_OID = "a1b2c3d4-0000-4000-8000-00000000c001"


def pid_of(object_id: str, customer: str = "contoso") -> str:
    return pseudonymizer().principal_id(
        cloud=CloudName.COMMERCIAL,
        customer_id=customer,
        tenant_id=TENANTS[customer],
        object_id=object_id,
        kind="user",
    )


def principal_id_for(who: Who) -> str:
    return pid_of(who.object_id, who.customer)


def bearer_for(dep: Deployment, object_id: str) -> dict[str, str]:
    token = dev_issuer(dep.customer).mint(audience=AUDIENCE, object_id=object_id, now=dep.clock.now)
    return {"Authorization": f"Bearer {token}"}


class Owners:
    """``ResourceDomainResolver`` over the suite's catalog item ids (item -> its domain)."""

    async def domain_of(self, scope: IdentityScope, resource_id: str) -> str | None:
        parts = resource_id.split(":")
        if len(parts) != 5 or parts[1] != scope.customer_id:
            return None
        name = parts[4].split("-", 1)[0]
        return domain_id(parts[1], name) if name in (FIN, OPS) else None


def install(world: World) -> World:
    """Install the identity plane on every deployment and seed the extra contoso admins."""
    for dep in world.deployments.values():
        configure_identity_admin(
            dep.app,
            IdentityAdminPlane(
                policy_admin=InMemoryPolicyAdminRepository(dep.repo),
                policy_reader=dep.repo,
                revocation=dep.service,
                audit=dep.audit_repo,
                resource_domains=Owners(),
                clock=dep.clock,
                cache_hooks=dep.hooks,
            ),
        )
    contoso = world["contoso"]
    fin = domain_id("contoso", FIN)
    control = customer_control_domain_id("commercial", "contoso")
    _seed(contoso, EXPIRED_ADMIN_OID, (fin,), Role.ADMIN, (fin,), expires_in=10)
    _seed(contoso, CUSTOMER_ADMIN_OID, (fin, control), Role.ADMIN, (fin, control))
    return world


def _seed(
    dep: Deployment,
    object_id: str,
    members: tuple[str, ...],
    role: Role,
    domains: tuple[str, ...],
    *,
    expires_in: float = 7 * 24 * 3600,
) -> None:
    principal = pid_of(object_id, dep.customer)
    dep.repo.put_principal(
        PrincipalPolicy(
            id=principal_document_id(principal),
            customer_id=dep.customer,
            principal_id=principal,
            domain_memberships=members,
            role_assignments=(
                PolicyRoleAssignment(
                    assignment_id="ra-seeded",
                    role=role,
                    domain_ids=domains,
                    expires_at=at(expires_in),
                ),
            ),
        )
    )


@pytest.fixture
def iworld(world: World) -> World:
    return install(world)


# ------------------------------------------------------------------ route table


def _ts(offset: float) -> str:
    return (at(0) + timedelta(seconds=offset)).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Route:
    name: str
    method: str
    path: Callable[[str], str]
    body: Callable[[str], dict[str, Any] | None]


def _role_body(target: str, role: str = "viewer", domain: str = FIN) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "op": "assign",
        "principal_id": target,
        "assignment_id": "ra-new",
        "role": role,
        "domain_ids": [domain_id(target.split(":")[1], domain, target.split(":")[0])],
        "expires_at": _ts(3600),
        "reason": "access_request",
    }


def _membership_body(target: str, domain: str = FIN) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "op": "add",
        "principal_id": target,
        "domain_id": domain_id(target.split(":")[1], domain, target.split(":")[0]),
        "reason": "access_request",
    }


def _grant_body(target: str, resource: str = FIN_AGENT) -> dict[str, Any]:
    customer = target.split(":")[1]
    return {
        "schema_version": "1.0.0",
        "principal_id": target,
        "grant_id": "g-new",
        "resource_id": resource.replace(":contoso:", f":{customer}:"),
        "permissions": ["read"],
        "expires_at": _ts(3600),
        "reason": "incident_review",
    }


def _fin(target: str) -> str:
    return domain_id(target.split(":")[1], FIN, target.split(":")[0])


POLICY_ROUTES: tuple[Route, ...] = (
    Route("list", "GET", lambda t: BASE, lambda t: None),
    Route("detail", "GET", lambda t: f"{BASE}/{t}", lambda t: None),
    Route("role_put", "PUT", lambda t: f"{BASE}/{t}/role-assignments/ra-new", _role_body),
    Route("role_delete", "DELETE", lambda t: f"{BASE}/{t}/role-assignments/ra-new", lambda t: None),
    Route(
        "membership_put",
        "PUT",
        lambda t: f"{BASE}/{t}/domain-memberships/{_fin(t)}",
        _membership_body,
    ),
    Route(
        "membership_delete",
        "DELETE",
        lambda t: f"{BASE}/{t}/domain-memberships/{_fin(t)}",
        lambda t: None,
    ),
    Route("grant_put", "PUT", lambda t: f"{BASE}/{t}/grants/g-new", _grant_body),
    Route("grant_delete", "DELETE", lambda t: f"{BASE}/{t}/grants/g-new", lambda t: None),
)
TARGETED = tuple(r for r in POLICY_ROUTES if r.name != "list")


def call(dep: Deployment, route: Route, target: str, headers: dict[str, str]) -> Any:
    body = route.body(target)
    return dep.client.request(
        route.method,
        route.path(target),
        headers=headers,
        json=body,
    )


def snapshot(dep: Deployment) -> tuple[Any, ...]:
    return (
        dict(dep.repo._principals),  # pyright: ignore[reportPrivateUsage]
        dict(dep.repo._heads),  # pyright: ignore[reportPrivateUsage]
    )


def denial_reasons(dep: Deployment) -> list[str]:
    return [a.reason for a in dep.recorder.attempts]


def etag_header(dep: Deployment, actor: dict[str, str], target: str) -> dict[str, str]:
    response = dep.client.get(f"{BASE}/{target}", headers=actor)
    if response.status_code != 200:
        return {}
    return {"If-Match": response.headers["ETag"]}


# ------------------------------------------------------------------ dimensions


@pytest.mark.parametrize("route", TARGETED, ids=lambda r: r.name)
@pytest.mark.parametrize("cloud", ["customer", "cloud"])
def test_cross_customer_and_cross_cloud_targets(iworld: World, route: Route, cloud: str) -> None:
    dep = iworld["contoso"]
    target = principal_id_for(FABRIKAM_ANALYST)
    if cloud == "cloud":
        target = principal_id_for(ANALYST).replace("commercial:", "government:", 1)
    before = snapshot(dep)
    response = call(dep, route, target, dep.bearer(ADMIN))
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "cross_scope_target"
    assert "cross_scope_target" in denial_reasons(dep)
    assert snapshot(dep) == before


CROSS_DOMAIN: dict[str, tuple[Callable[[str], dict[str, Any] | None], str]] = {
    "role_put": (lambda t: _role_body(t, domain=OPS), "target_out_of_scope"),
    "membership_put": (lambda t: _membership_body(t, domain=OPS), "target_out_of_scope"),
    "grant_put": (lambda t: _grant_body(t, resource=OPS_AGENT), "target_out_of_scope"),
}


@pytest.mark.parametrize("name", sorted(CROSS_DOMAIN))
def test_cross_domain_writes(iworld: World, name: str) -> None:
    dep = iworld["contoso"]
    route = next(r for r in POLICY_ROUTES if r.name == name)
    target = principal_id_for(ANALYST)
    body_fn, reason = CROSS_DOMAIN[name]
    path = route.path(target)
    if name == "membership_put":
        path = f"{BASE}/{target}/domain-memberships/{domain_id('contoso', OPS)}"
    actor = dep.bearer(ADMIN)
    before = snapshot(dep)
    response = dep.client.request(
        "PUT", path, headers={**actor, **etag_header(dep, actor, target)}, json=body_fn(target)
    )
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == reason
    assert reason in denial_reasons(dep)
    assert snapshot(dep) == before


@pytest.mark.parametrize("name", ["detail", "role_delete", "membership_delete", "grant_delete"])
def test_cross_domain_reads_and_removes(iworld: World, name: str) -> None:
    """An operations-only principal is invisible to a finance admin; removes on it are refused."""
    dep = iworld["contoso"]
    route = next(r for r in POLICY_ROUTES if r.name == name)
    target = principal_id_for(OPS_ANALYST)
    path = route.path(target)
    if name == "membership_delete":
        path = f"{BASE}/{target}/domain-memberships/{domain_id('contoso', OPS)}"
    if name == "role_delete":
        path = f"{BASE}/{target}/role-assignments/ra-{OPS_ANALYST.label}"
    actor = dep.bearer(ADMIN)
    before = snapshot(dep)
    current = run(InMemoryPolicyAdminRepository(dep.repo).get_with_etag("contoso", target))
    headers = {**actor, "If-Match": current[1]} if current else actor
    response = dep.client.request(route.method, path, headers=headers)
    assert response.status_code in (403, 404), response.text
    if response.status_code == 403:
        assert response.json()["reason"] == "target_out_of_scope"
    assert snapshot(dep) == before


def test_list_hides_other_domains(iworld: World) -> None:
    dep = iworld["contoso"]
    response = dep.client.get(BASE, headers=dep.bearer(ADMIN))
    assert response.status_code == 200
    ids = {i["principal"]["principal_id"] for i in response.json()["items"]}
    assert principal_id_for(ANALYST) in ids
    assert principal_id_for(OPS_ANALYST) not in ids
    assert "fabrikam" not in response.text and "operations" not in response.text


@pytest.mark.parametrize("route", TARGETED, ids=lambda r: r.name)
def test_self_modification(iworld: World, route: Route) -> None:
    dep = iworld["contoso"]
    me = principal_id_for(ADMIN)
    actor = dep.bearer(ADMIN)
    before = snapshot(dep)
    headers = {**actor, **etag_header(dep, actor, me)}
    response = call(dep, route, me, headers)
    if route.method == "GET":
        assert response.status_code == 200  # reading your own access is not a change
        return
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "self_modification_forbidden"
    assert "self_modification_forbidden" in denial_reasons(dep)
    assert snapshot(dep) == before


@pytest.mark.parametrize("role", ["admin", "security_auditor"])
def test_privileged_role_without_customer_scope(iworld: World, role: str) -> None:
    dep = iworld["contoso"]
    target = principal_id_for(ANALYST)
    actor = dep.bearer(ADMIN)
    before = snapshot(dep)
    response = dep.client.put(
        f"{BASE}/{target}/role-assignments/ra-new",
        headers={**actor, **etag_header(dep, actor, target)},
        json=_role_body(target, role=role),
    )
    assert response.status_code == 403
    assert response.json()["reason"] == "customer_scope_required"
    assert "customer_scope_required" in denial_reasons(dep)
    assert snapshot(dep) == before


def test_removing_a_privileged_assignment_needs_customer_scope(iworld: World) -> None:
    dep = iworld["contoso"]
    target = pid_of(EXPIRED_ADMIN_OID)
    actor = dep.bearer(ADMIN)
    before = snapshot(dep)
    response = dep.client.delete(
        f"{BASE}/{target}/role-assignments/ra-seeded",
        headers={**actor, **etag_header(dep, actor, target)},
    )
    assert response.status_code == 403
    assert response.json()["reason"] == "customer_scope_required"
    assert snapshot(dep) == before


def test_customer_control_membership_needs_customer_scope(iworld: World) -> None:
    dep = iworld["contoso"]
    target = principal_id_for(ANALYST)
    control = customer_control_domain_id("commercial", "contoso")
    body = {**_membership_body(target), "domain_id": control}
    actor = dep.bearer(ADMIN)
    before = snapshot(dep)
    response = dep.client.put(
        f"{BASE}/{target}/domain-memberships/{control}",
        headers={**actor, **etag_header(dep, actor, target)},
        json=body,
    )
    assert response.status_code == 403
    assert snapshot(dep) == before
    customer_admin = bearer_for(dep, CUSTOMER_ADMIN_OID)
    allowed = dep.client.put(
        f"{BASE}/{target}/domain-memberships/{control}",
        headers={**customer_admin, **etag_header(dep, customer_admin, target)},
        json=body,
    )
    assert allowed.status_code == 200, allowed.text


@pytest.mark.parametrize("route", POLICY_ROUTES, ids=lambda r: r.name)
def test_expired_assignment(iworld: World, route: Route) -> None:
    dep = iworld["contoso"]
    iworld.clock.advance(11)  # the seeded admin assignment lapsed
    before = snapshot(dep)
    response = call(dep, route, principal_id_for(ANALYST), bearer_for(dep, EXPIRED_ADMIN_OID))
    assert response.status_code == 403
    assert response.json()["reason"] == "permission_missing"
    assert "permission_missing" in denial_reasons(dep)
    assert snapshot(dep) == before


@pytest.mark.parametrize("route", POLICY_ROUTES, ids=lambda r: r.name)
def test_revoked_actor(iworld: World, route: Route) -> None:
    dep = iworld["contoso"]
    token = dep.bearer(ADMIN)
    dep.revoke(Who("contoso", FIN, Role.ADMIN), ADMIN)
    before = snapshot(dep)
    response = call(dep, route, principal_id_for(ANALYST), token)
    assert response.status_code == 403
    assert response.json()["reason"] == "principal_revoked"
    assert snapshot(dep) == before


@pytest.mark.parametrize("route", POLICY_ROUTES, ids=lambda r: r.name)
def test_no_policy_manage(iworld: World, route: Route) -> None:
    dep = iworld["contoso"]
    steward = Who("contoso", FIN, Role.DOMAIN_STEWARD)  # holds grant.write, not policy.manage
    before = snapshot(dep)
    response = call(dep, route, principal_id_for(ANALYST), dep.bearer(steward))
    assert response.status_code == 403
    assert response.json()["reason"] == "permission_missing"
    assert snapshot(dep) == before
