"""ABAC negative suite for the connector admin routes (PRP-42 item 5).

The suite world serves the real application router table, so ``/api/v1/admin/sources/connectors``
is mounted; this module installs the connector plane on each deployment and asserts that every
route refuses, per dimension, with a recorded denial and no write:

=================================  ==========================================================
Dimension                          Expected refusal
=================================  ==========================================================
no role (viewer, analyst, steward) 403 ``permission_missing``
security auditor                   403 (holds no ``config.manage``)
ordinary domain admin              403 ``customer_scope_required``
expired control-domain admin       403 ``permission_missing``
other customer                     404 / 401 / 422 ``cross_customer`` (never another's config)
other cloud                        422 ``cross_cloud`` (nothing stored)
=================================  ==========================================================
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from neurosphere_api.admin.sources.connectors import (
    ConnectorAdminPlane,
    configure_admin_connectors,
)
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.admin.connectors import ConnectorConfigAdmin
from neurosphere_core.auth.scope import (
    PolicyRoleAssignment,
    PrincipalPolicy,
    Role,
    customer_control_domain_id,
    principal_document_id,
)
from neurosphere_workers.connector_config import VALIDATORS

from .test_admin_identity import pid_of
from .world import AUDIENCE, Deployment, Who, World, at, dev_issuer, domain_id, run

BASE = "/api/v1/admin/sources/connectors"
FIN = "finance"
CONTROL_ADMIN_OID = "a1b2c3d4-0000-4000-8000-00000000c101"
EXPIRED_CONTROL_OID = "a1b2c3d4-0000-4000-8000-00000000e101"
VAULT = "https://ns-kv.vault.azure.net/secrets/producer-key"
GOV_VAULT = "https://ns-kv.vault.usgovcloudapi.net/secrets/producer-key"
ADMIN = Who("contoso", FIN, Role.ADMIN)
DENIED_ROLES = (Role.VIEWER, Role.ANALYST, Role.DOMAIN_STEWARD, Role.SECURITY_AUDITOR)


def _bearer(dep: Deployment, object_id: str) -> dict[str, str]:
    token = dev_issuer(dep.customer).mint(audience=AUDIENCE, object_id=object_id, now=dep.clock.now)
    return {"Authorization": f"Bearer {token}"}


def _seed(dep: Deployment, object_id: str, *, expires_in: float) -> None:
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


def body(customer: str = "contoso", **over: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "connector_id": "gateway-main",
        "connector_kind": "gateway_poll",
        "domain_ids": [domain_id(customer, FIN)],
        "settings": {"api_base_url": "https://api.example.test"},
        "credential": {"kind": "key_vault_secret", "secret_uri": VAULT},
        "enabled": True,
    }
    result.update(over)
    return result


@dataclass
class Plane:
    repository: InMemoryAdminConfigRepository


@pytest.fixture
def cworld(world: World) -> tuple[World, dict[str, Plane]]:
    planes: dict[str, Plane] = {}
    for name, dep in world.deployments.items():
        repository = InMemoryAdminConfigRepository(cloud="commercial")
        admin = ConnectorConfigAdmin(repository, cloud="commercial", validators=VALIDATORS)
        configure_admin_connectors(
            dep.app, ConnectorAdminPlane(admin=admin, audit=lambda dep=dep: dep.audit_repo)
        )
        planes[name] = Plane(repository)
        _seed(dep, CONTROL_ADMIN_OID, expires_in=7 * 24 * 3600)
        _seed(dep, EXPIRED_CONTROL_OID, expires_in=10)
    return world, planes


@dataclass(frozen=True)
class Route:
    name: str
    method: str
    path: str
    json: Callable[[], dict[str, Any] | None]


ROUTES: tuple[Route, ...] = (
    Route("create", "POST", BASE, body),
    Route("list", "GET", BASE, lambda: None),
    Route("get", "GET", f"{BASE}/gateway-main", lambda: None),
    Route("replace", "PUT", f"{BASE}/gateway-main", body),
    Route("enable", "POST", f"{BASE}/gateway-main/enable", lambda: None),
    Route("disable", "POST", f"{BASE}/gateway-main/disable", lambda: None),
    Route("retire", "DELETE", f"{BASE}/gateway-main", lambda: None),
)


def _call(dep: Deployment, route: Route, headers: dict[str, str]) -> Any:
    return dep.client.request(
        route.method, route.path, headers={**headers, "If-Match": '"x"'}, json=route.json()
    )


def _stored(plane: Plane, customer: str = "contoso") -> list[Any]:
    return run(plane.repository.list_by_kind(customer, "connector_config", include_retired=True))


def _reasons(dep: Deployment) -> list[str]:
    return [a.reason for a in dep.recorder.attempts]


# ------------------------------------------------------------------ dimensions


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
@pytest.mark.parametrize("role", DENIED_ROLES, ids=lambda r: r.value)
def test_roles_without_config_manage_are_denied(
    cworld: tuple[World, dict[str, Plane]], route: Route, role: Role
) -> None:
    world, planes = cworld
    dep = world["contoso"]
    response = _call(dep, route, dep.bearer(Who("contoso", FIN, role)))
    assert response.status_code == 403, response.text
    assert _reasons(dep), "a denial record is written"
    assert _stored(planes["contoso"]) == []


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_ordinary_domain_admin_needs_customer_scope(
    cworld: tuple[World, dict[str, Plane]], route: Route
) -> None:
    world, planes = cworld
    dep = world["contoso"]
    response = _call(dep, route, dep.bearer(ADMIN))
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "customer_scope_required"
    assert "customer_scope_required" in _reasons(dep)
    assert _stored(planes["contoso"]) == []


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_expired_control_domain_admin_is_denied(
    cworld: tuple[World, dict[str, Plane]], route: Route
) -> None:
    world, planes = cworld
    dep = world["contoso"]
    world.clock.advance(11)
    response = _call(dep, route, _bearer(dep, EXPIRED_CONTROL_OID))
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "permission_missing"
    assert "permission_missing" in _reasons(dep)
    assert _stored(planes["contoso"]) == []


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_no_token_is_401(cworld: tuple[World, dict[str, Plane]], route: Route) -> None:
    world, _ = cworld
    assert _call(world["contoso"], route, {}).status_code == 401


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_other_customer_token_is_not_accepted(
    cworld: tuple[World, dict[str, Plane]], route: Route
) -> None:
    world, planes = cworld
    contoso, fabrikam = world["contoso"], world["fabrikam"]
    assert _call(fabrikam, route, _bearer(contoso, CONTROL_ADMIN_OID)).status_code == 401
    assert _stored(planes["fabrikam"], "fabrikam") == []


def test_other_customer_cannot_see_or_name_anothers_config(
    cworld: tuple[World, dict[str, Plane]],
) -> None:
    world, planes = cworld
    contoso, fabrikam = world["contoso"], world["fabrikam"]
    created = contoso.client.post(BASE, headers=_bearer(contoso, CONTROL_ADMIN_OID), json=body())
    assert created.status_code == 201, created.text
    headers = _bearer(fabrikam, CONTROL_ADMIN_OID)
    assert fabrikam.client.get(f"{BASE}/gateway-main", headers=headers).status_code == 404
    assert fabrikam.client.get(BASE, headers=headers).json()["items"] == []
    cross = fabrikam.client.post(BASE, headers=headers, json=body("contoso"))
    assert cross.status_code == 422, cross.text
    assert _stored(planes["fabrikam"], "fabrikam") == []


def test_other_cloud_references_and_domains_are_refused(
    cworld: tuple[World, dict[str, Plane]],
) -> None:
    world, planes = cworld
    dep = world["contoso"]
    headers = _bearer(dep, CONTROL_ADMIN_OID)
    government_vault = body(credential={"kind": "key_vault_secret", "secret_uri": GOV_VAULT})
    government_domain = body(domain_ids=[domain_id("contoso", FIN, "government")])
    for payload in (government_vault, government_domain):
        response = dep.client.post(BASE, headers=headers, json=payload)
        assert response.status_code == 422, response.text
    assert _stored(planes["contoso"]) == []


def test_customer_level_admin_is_allowed(cworld: tuple[World, dict[str, Plane]]) -> None:
    world, planes = cworld
    dep = world["contoso"]
    response = dep.client.post(BASE, headers=_bearer(dep, CONTROL_ADMIN_OID), json=body())
    assert response.status_code == 201, response.text
    assert len(_stored(planes["contoso"])) == 1


def monitor_body() -> dict[str, Any]:
    return body(
        connector_id="azure-monitor-ai",
        connector_kind="azure_monitor_ai",
        settings={
            "workspace_ids": "11111111-2222-4333-8444-555555555555",
            "api_base_url": "https://api.example.test",
        },
    )


@pytest.mark.parametrize("role", DENIED_ROLES, ids=lambda r: r.value)
def test_azure_monitor_ai_create_needs_config_manage(
    cworld: tuple[World, dict[str, Plane]], role: Role
) -> None:
    world, planes = cworld
    dep = world["contoso"]
    response = dep.client.post(
        BASE, headers=dep.bearer(Who("contoso", FIN, role)), json=monitor_body()
    )
    assert response.status_code == 403, response.text
    assert _reasons(dep), "a denial record is written"
    assert _stored(planes["contoso"]) == []


def test_azure_monitor_ai_create_needs_customer_scope_and_is_audited(
    cworld: tuple[World, dict[str, Plane]],
) -> None:
    world, planes = cworld
    dep = world["contoso"]
    response = dep.client.post(BASE, headers=dep.bearer(ADMIN), json=monitor_body())
    assert response.status_code == 403, response.text
    assert "customer_scope_required" in _reasons(dep)
    assert _stored(planes["contoso"]) == []


def test_azure_monitor_ai_customer_admin_creates_and_managed_identity_is_422(
    cworld: tuple[World, dict[str, Plane]],
) -> None:
    world, planes = cworld
    dep = world["contoso"]
    headers = _bearer(dep, CONTROL_ADMIN_OID)
    identity = {
        "kind": "managed_identity",
        "managed_identity_client_id": "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5",
    }
    refused = dep.client.post(
        BASE, headers=headers, json={**monitor_body(), "credential": identity}
    )
    assert refused.status_code == 422, refused.text
    assert _stored(planes["contoso"]) == []
    created = dep.client.post(BASE, headers=headers, json=monitor_body())
    assert created.status_code == 201, created.text
    assert len(_stored(planes["contoso"])) == 1
