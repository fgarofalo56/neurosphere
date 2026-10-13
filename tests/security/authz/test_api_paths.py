"""API path: every route denies cross-domain, cross-customer and forged-input requests."""

import pytest
from neurosphere_api.authz import route_inventory, undeclared_routes, verify_route_permissions

from .cases import API_CASES, ApiCase, ScenarioCase, scenario_cases
from .executors import LIFECYCLE_SCENARIOS, run_api_case, run_lifecycle
from .world import World

PLAIN = [c for c in API_CASES if ".priv." not in c.id]
LIFECYCLE = [c for c in scenario_cases("api") if c.scenario in LIFECYCLE_SCENARIOS]


@pytest.mark.parametrize("case", PLAIN, ids=lambda c: c.id)
def test_api_case(ro_world: World, case: ApiCase) -> None:
    run_api_case(ro_world, case)


@pytest.mark.parametrize("case", LIFECYCLE, ids=lambda c: c.id)
def test_api_lifecycle(case: ScenarioCase) -> None:
    run_lifecycle("api", case)


def test_every_route_declares_a_permission(ro_world: World) -> None:
    app = ro_world["contoso"].app
    assert undeclared_routes(app) == ()
    verify_route_permissions(app)
    declared = {e.path for e in route_inventory(app) if e.permissions}
    assert {"/d/items", "/d/query", "/d/export", "/d/config"} <= declared
    assert any(p.startswith("/audit/") for p in declared)


def test_denials_are_recorded_by_the_recorder_hook(ro_world: World) -> None:
    dep = ro_world["contoso"]
    assert dep.recorder.attempts, "the DenialRecorder hook was never invoked by the matrix"
    for attempt in dep.recorder.attempts:
        assert attempt.scope.customer_id == "contoso", (
            "a denial was recorded under another customer"
        )
