"""Push interface (C13): PushSessionRegistry only; the gateway is PRP-18, so a fake is used."""

import pytest
from neurosphere_core.scope import IdentityScope

from .cases import ScenarioCase, scenario_cases
from .executors import LIFECYCLE_SCENARIOS, run_lifecycle, run_push_scenario
from .world import Who, World

ROWS = scenario_cases("push")
PLAIN = [c for c in ROWS if c.scenario not in LIFECYCLE_SCENARIOS and ".priv." not in c.id]
LIFECYCLE = [c for c in ROWS if c.scenario in LIFECYCLE_SCENARIOS]


@pytest.mark.parametrize("case", PLAIN, ids=lambda c: c.id)
def test_push_case(ro_world: World, scopes: dict[Who, IdentityScope], case: ScenarioCase) -> None:
    run_push_scenario(ro_world, scopes, case)


@pytest.mark.parametrize("case", LIFECYCLE, ids=lambda c: c.id)
def test_push_lifecycle(case: ScenarioCase) -> None:
    run_lifecycle("push", case)
