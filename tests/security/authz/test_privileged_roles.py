"""Privileged roles (C7): Admin and Auditor have no bypass; a scoped grant opens one resource."""

import pytest
from neurosphere_core.auth.scope import (
    ROLE_PERMISSIONS,
    Permission,
    PolicyGrant,
    PolicyRoleAssignment,
    Role,
)
from neurosphere_core.scope import IdentityScope
from pydantic import ValidationError

from .cases import (
    ADMIN_C_FIN,
    API_CASES,
    EXPORT_CASES,
    SEARCH_CASES,
    ApiCase,
    ExportCase,
    ScenarioCase,
    SearchCase,
    scenario_cases,
)
from .executors import (
    run_api_case,
    run_cache_scenario,
    run_export_case,
    run_priv_api_scenario,
    run_push_scenario,
    run_search_case,
)
from .world import Who, World, at, build_world, domain_id, make_grant

PRIV_API = [c for c in API_CASES if ".priv." in c.id]
PRIV_SEARCH = [c for c in SEARCH_CASES if ".priv." in c.id]
PRIV_EXPORT = [c for c in EXPORT_CASES if ".priv." in c.id]
PRIV_API_SCENARIOS = [c for c in scenario_cases("api") if ".priv." in c.id]
PRIV_CACHE = [c for c in scenario_cases("cache") if ".priv." in c.id]
PRIV_PUSH = [c for c in scenario_cases("push") if ".priv." in c.id]


def _world(request: pytest.FixtureRequest, name: str) -> World:
    world = request.getfixturevalue("ro_world" if name == "ro" else "grant_world")
    assert isinstance(world, World)
    return world


@pytest.mark.parametrize("case", PRIV_API, ids=lambda c: c.id)
def test_priv_api(request: pytest.FixtureRequest, case: ApiCase) -> None:
    run_api_case(_world(request, case.world), case)


@pytest.mark.parametrize("case", PRIV_API_SCENARIOS, ids=lambda c: c.id)
def test_priv_api_scenarios(case: ScenarioCase) -> None:
    run_priv_api_scenario(case)


@pytest.mark.parametrize("case", PRIV_SEARCH, ids=lambda c: c.id)
def test_priv_search(request: pytest.FixtureRequest, case: SearchCase) -> None:
    run_search_case(_world(request, case.world), case)


@pytest.mark.parametrize("case", PRIV_EXPORT, ids=lambda c: c.id)
def test_priv_export(request: pytest.FixtureRequest, case: ExportCase) -> None:
    run_export_case(_world(request, case.world), case)


@pytest.mark.parametrize("case", PRIV_CACHE, ids=lambda c: c.id)
def test_priv_cache(ro_world: World, scopes: dict[Who, IdentityScope], case: ScenarioCase) -> None:
    run_cache_scenario(ro_world, scopes, case)


@pytest.mark.parametrize("case", PRIV_PUSH, ids=lambda c: c.id)
def test_priv_push(ro_world: World, scopes: dict[Who, IdentityScope], case: ScenarioCase) -> None:
    run_push_scenario(ro_world, scopes, case)


# ------------------------------------------------------------------ structural (no bypass)


def test_no_role_holds_every_permission() -> None:
    everything = set(Permission)
    for role, permissions in ROLE_PERMISSIONS.items():
        assert set(permissions) != everything, f"{role} is a superuser"


def test_admin_and_auditor_are_disjoint_in_the_sensitive_directions() -> None:
    admin, auditor = ROLE_PERMISSIONS[Role.ADMIN], ROLE_PERMISSIONS[Role.SECURITY_AUDITOR]
    assert Permission.DATA_EXPORT not in admin
    assert Permission.AUDIT_READ not in admin and Permission.EVIDENCE_READ not in admin
    assert Permission.DATA_READ not in auditor and Permission.DATA_EXPORT not in auditor
    assert not admin & auditor


@pytest.mark.parametrize("role", [Role.ADMIN, Role.SECURITY_AUDITOR])
def test_privileged_assignments_must_be_time_bound(role: Role) -> None:
    dom = domain_id("contoso", "finance")
    with pytest.raises(ValidationError):
        PolicyRoleAssignment(assignment_id="ra-x", role=role, domain_ids=(dom,))
    ok = PolicyRoleAssignment(assignment_id="ra-x", role=role, domain_ids=(dom,), expires_at=at(60))
    assert ok.expires_at is not None


def test_grants_must_name_one_resource_carry_a_reason_and_expire() -> None:
    base = {
        "grant_id": "g-1",
        "resource_id": "commercial:contoso:catalog:agent:finance-triage-1",
        "permissions": ["read"],
        "expires_at": at(60),
        "reason": "incident review INC-42",
    }
    assert PolicyGrant.model_validate(base)
    for missing in ("expires_at", "reason", "resource_id"):
        broken = {k: v for k, v in base.items() if k != missing}
        with pytest.raises(ValidationError):
            PolicyGrant.model_validate(broken)
    for wildcard in ("*", "commercial:contoso:catalog:agent:*"):
        with pytest.raises(ValidationError):
            PolicyGrant.model_validate({**base, "resource_id": wildcard})


def test_a_grant_naming_a_domain_does_not_open_the_domain() -> None:
    """The policy model accepts a domain id as a grant target; derivation must drop it."""
    ops = domain_id("contoso", "operations")
    world = build_world(grants={ADMIN_C_FIN: (make_grant(ops, "read"),)})
    dep = world["contoso"]
    scope = dep.scope(ADMIN_C_FIN)
    assert scope.to_contract().allowed_resources == []
    response = dep.client.get(f"/d/domains/{ops}/items", headers=dep.bearer(ADMIN_C_FIN))
    assert response.status_code == 403
    assert response.json()["reason"] == "target_out_of_scope"
