"""Export path: the export function and its route use the same scope and deny out-of-scope."""

import pytest

from .cases import EXPORT_CASES, ExportCase, ScenarioCase, scenario_cases
from .executors import LIFECYCLE_SCENARIOS, run_export_case, run_lifecycle
from .world import World

PLAIN = [c for c in EXPORT_CASES if ".priv." not in c.id]
LIFECYCLE = [c for c in scenario_cases("export") if c.scenario in LIFECYCLE_SCENARIOS]


@pytest.mark.parametrize("case", PLAIN, ids=lambda c: c.id)
def test_export_case(ro_world: World, case: ExportCase) -> None:
    run_export_case(ro_world, case)


@pytest.mark.parametrize("case", LIFECYCLE, ids=lambda c: c.id)
def test_export_lifecycle(case: ScenarioCase) -> None:
    run_lifecycle("export", case)
