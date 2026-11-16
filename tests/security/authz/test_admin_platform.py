"""ABAC negative suite for the platform admin routes (PRP-44 item 6).

The suite world serves the real application router table, so ``/api/v1/admin/platform`` is
mounted; this module installs the platform plane on each deployment and asserts that every route
refuses, per dimension, with a recorded denial and no write:

=================================  ==========================================================
Dimension                          Expected refusal
=================================  ==========================================================
no role (viewer, analyst, steward) 403 ``permission_missing``
security auditor                   403 (holds no ``config.manage``)
ordinary domain admin              403 ``customer_scope_required``
expired control-domain admin       403 ``permission_missing``
no token                           401
other customer                     401 (token), 422 ``cross_customer`` (named domain)
other cloud                        422 ``cross_cloud`` (nothing stored)
=================================  ==========================================================
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from neurosphere_api.admin.platform import PlatformAdminPlane, configure_admin_platform
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.admin.platform import (
    BudgetAdmin,
    DomainAdmin,
    DomainRegistry,
    PlatformAdmin,
    PriceSheetAdmin,
    ReviewPolicyAdmin,
)
from neurosphere_core.auth.scope import (
    PolicyRoleAssignment,
    PrincipalPolicy,
    Role,
    customer_control_domain_id,
    principal_document_id,
)
from neurosphere_core.pricing import InMemoryPriceSnapshotStore

from .test_admin_identity import pid_of
from .world import AUDIENCE, Deployment, Who, World, at, dev_issuer, domain_id, run

BASE = "/api/v1/admin/platform"
FIN = "finance"
CONTROL_ADMIN_OID = "a1b2c3d4-0000-4000-8000-00000000c201"
EXPIRED_CONTROL_OID = "a1b2c3d4-0000-4000-8000-00000000e201"
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


def domain_body(
    customer: str = "contoso", cloud: str = "commercial", **over: Any
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "domain_id": domain_id(customer, FIN, cloud),
        "display_name": "Finance",
        "classification": "internal",
        "residency_region": "eastus2",
        "status": "active",
        "is_control_domain": False,
    }
    result.update(over)
    return result


def budget_body(**over: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "budget_id": "fin-monthly",
        "domain_id": domain_id("contoso", FIN),
        "period": "monthly",
        "amount": "100",
        "currency": "USD",
        "thresholds_percent": [80, 100],
    }
    result.update(over)
    return result


def sheet_body(**over: Any) -> dict[str, Any]:
    row = {
        "service_name": "Azure OpenAI",
        "sku_name": "x",
        "unit_of_measure": "1M",
        "retail_price": "1.23",
    }
    meter = {"provider": "azure_openai", "model": "gpt-x"}
    result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "snapshot_id": "sheet-1",
        "source": "provider_price_sheet",
        "source_url": "https://example.test/prices",
        "retrieval_date": "2026-11-01",
        "effective_date": "2026-11-01",
        "currency": "USD",
        "clouds": ["commercial"],
        "synthetic": False,
        "notes": "",
        "rows": [
            {**row, "token_meter": {**meter, "kind": "input"}},
            {**row, "token_meter": {**meter, "kind": "output"}},
        ],
    }
    result.update(over)
    return result


def policy_body() -> dict[str, Any]:
    settings = {
        "self_approval_forbidden": True,
        "approver_permission": "action.approve",
        "assignment_timeout_seconds": 14400,
        "sla_seconds": 3600,
        "escalation_step_seconds": 7200,
        "max_escalations": 2,
        "expiry_seconds": 86400,
    }
    return {
        "schema_version": "1.0.0",
        "policy_version": "x",
        "kind_defaults": [{"review_kind": "maker_checker", "policy": settings}],
        "action_overrides": [],
    }


@dataclass
class Plane:
    repository: InMemoryAdminConfigRepository
    prices: InMemoryPriceSnapshotStore


@pytest.fixture
def pworld(world: World) -> tuple[World, dict[str, Plane]]:
    planes: dict[str, Plane] = {}
    for name, dep in world.deployments.items():
        repository = InMemoryAdminConfigRepository(cloud="commercial")
        prices = InMemoryPriceSnapshotStore()
        registry = DomainRegistry(repository)
        admin = PlatformAdmin(
            domains=DomainAdmin(repository, cloud="commercial"),
            registry=registry,
            budgets=BudgetAdmin(repository, registry),
            price_sheets=PriceSheetAdmin(prices, cloud="commercial"),
            review_policy=ReviewPolicyAdmin(repository),
        )
        configure_admin_platform(
            dep.app, PlatformAdminPlane(admin=admin, audit=lambda dep=dep: dep.audit_repo)
        )
        planes[name] = Plane(repository, prices)
        _seed(dep, CONTROL_ADMIN_OID, expires_in=7 * 24 * 3600)
        _seed(dep, EXPIRED_CONTROL_OID, expires_in=10)
    return world, planes


@dataclass(frozen=True)
class Route:
    name: str
    method: str
    path: str
    json: Callable[[], dict[str, Any] | None]


DOMAIN = domain_id("contoso", FIN)
ROUTES: tuple[Route, ...] = (
    Route("domain-create", "POST", f"{BASE}/domains", domain_body),
    Route("domain-list", "GET", f"{BASE}/domains", lambda: None),
    Route("domain-get", "GET", f"{BASE}/domains/{DOMAIN}", lambda: None),
    Route("domain-retire", "POST", f"{BASE}/domains/{DOMAIN}/retire", lambda: None),
    Route("budget-create", "POST", f"{BASE}/budgets", budget_body),
    Route("budget-list", "GET", f"{BASE}/budgets", lambda: None),
    Route("budget-get", "GET", f"{BASE}/budgets/fin-monthly", lambda: None),
    Route("budget-put", "PUT", f"{BASE}/budgets/fin-monthly", budget_body),
    Route("budget-delete", "DELETE", f"{BASE}/budgets/fin-monthly", lambda: None),
    Route("sheet-upload", "POST", f"{BASE}/price-sheets", sheet_body),
    Route("sheet-list", "GET", f"{BASE}/price-sheets", lambda: None),
    Route("sheet-get", "GET", f"{BASE}/price-sheets/sheet-1", lambda: None),
    Route("sheet-coverage", "GET", f"{BASE}/price-sheets/sheet-1/coverage", lambda: None),
    Route("policy-get", "GET", f"{BASE}/review-policy", lambda: None),
    Route("policy-put", "PUT", f"{BASE}/review-policy", policy_body),
)


def _call(dep: Deployment, route: Route, headers: dict[str, str]) -> Any:
    return dep.client.request(
        route.method, route.path, headers={**headers, "If-Match": '"x"'}, json=route.json()
    )


def _stored(plane: Plane) -> int:
    kinds = ("domain", "budget", "review_policy")
    docs = sum(
        len(run(plane.repository.list_by_kind("contoso", k, include_retired=True))) for k in kinds
    )
    return docs + len(plane.prices.list_snapshots())


def _reasons(dep: Deployment) -> list[str]:
    return [a.reason for a in dep.recorder.attempts]


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
@pytest.mark.parametrize("role", DENIED_ROLES, ids=lambda r: r.value)
def test_roles_without_config_manage_are_denied(
    pworld: tuple[World, dict[str, Plane]], route: Route, role: Role
) -> None:
    world, planes = pworld
    dep = world["contoso"]
    response = _call(dep, route, dep.bearer(Who("contoso", FIN, role)))
    assert response.status_code == 403, response.text
    assert _reasons(dep), "a denial record is written"
    assert _stored(planes["contoso"]) == 0


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_ordinary_domain_admin_needs_customer_scope(
    pworld: tuple[World, dict[str, Plane]], route: Route
) -> None:
    world, planes = pworld
    dep = world["contoso"]
    response = _call(dep, route, dep.bearer(ADMIN))
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "customer_scope_required"
    assert "customer_scope_required" in _reasons(dep)
    assert _stored(planes["contoso"]) == 0


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_expired_control_domain_admin_is_denied(
    pworld: tuple[World, dict[str, Plane]], route: Route
) -> None:
    world, planes = pworld
    dep = world["contoso"]
    world.clock.advance(11)
    response = _call(dep, route, _bearer(dep, EXPIRED_CONTROL_OID))
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "permission_missing"
    assert _stored(planes["contoso"]) == 0


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_no_token_is_401(pworld: tuple[World, dict[str, Plane]], route: Route) -> None:
    world, _ = pworld
    assert _call(world["contoso"], route, {}).status_code == 401


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_other_customer_token_is_not_accepted(
    pworld: tuple[World, dict[str, Plane]], route: Route
) -> None:
    world, planes = pworld
    contoso, fabrikam = world["contoso"], world["fabrikam"]
    assert _call(fabrikam, route, _bearer(contoso, CONTROL_ADMIN_OID)).status_code == 401
    assert _stored(planes["fabrikam"]) == 0


def test_other_customer_cannot_register_or_budget_anothers_domain(
    pworld: tuple[World, dict[str, Plane]],
) -> None:
    world, planes = pworld
    fabrikam = world["fabrikam"]
    headers = _bearer(fabrikam, CONTROL_ADMIN_OID)
    cross = fabrikam.client.post(f"{BASE}/domains", headers=headers, json=domain_body("contoso"))
    assert cross.status_code == 422, cross.text
    assert fabrikam.client.get(f"{BASE}/domains", headers=headers).json()["items"] == []
    assert fabrikam.client.get(f"{BASE}/budgets/fin-monthly", headers=headers).status_code == 404
    assert _stored(planes["fabrikam"]) == 0


def test_other_cloud_domain_and_price_sheet_are_refused(
    pworld: tuple[World, dict[str, Plane]],
) -> None:
    world, planes = pworld
    dep = world["contoso"]
    headers = _bearer(dep, CONTROL_ADMIN_OID)
    government_domain = dep.client.post(
        f"{BASE}/domains", headers=headers, json=domain_body(cloud="government")
    )
    government_sheet = dep.client.post(
        f"{BASE}/price-sheets", headers=headers, json=sheet_body(clouds=["government"])
    )
    assert government_domain.status_code == 422, government_domain.text
    assert government_sheet.status_code == 422, government_sheet.text
    assert _stored(planes["contoso"]) == 0


def test_customer_level_admin_is_allowed(pworld: tuple[World, dict[str, Plane]]) -> None:
    world, planes = pworld
    dep = world["contoso"]
    headers = _bearer(dep, CONTROL_ADMIN_OID)
    assert (
        dep.client.post(f"{BASE}/domains", headers=headers, json=domain_body()).status_code == 201
    )
    assert (
        dep.client.post(f"{BASE}/price-sheets", headers=headers, json=sheet_body()).status_code
        == 201
    )
    assert _stored(planes["contoso"]) >= 3
