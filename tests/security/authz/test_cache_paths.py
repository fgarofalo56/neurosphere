"""Cache path: scope-keyed keys never collide across users, domains, customers, versions."""

import pytest
from neurosphere_core.scope import IdentityScope

from .cases import ScenarioCase, scenario_cases
from .executors import LIFECYCLE_SCENARIOS, run_cache_scenario, run_lifecycle
from .world import Who, World

ROWS = scenario_cases("cache")
PLAIN = [c for c in ROWS if c.scenario not in LIFECYCLE_SCENARIOS and ".priv." not in c.id]
LIFECYCLE = [c for c in ROWS if c.scenario in LIFECYCLE_SCENARIOS]


@pytest.mark.parametrize("case", PLAIN, ids=lambda c: c.id)
def test_cache_case(ro_world: World, scopes: dict[Who, IdentityScope], case: ScenarioCase) -> None:
    run_cache_scenario(ro_world, scopes, case)


@pytest.mark.parametrize("case", LIFECYCLE, ids=lambda c: c.id)
def test_cache_lifecycle(case: ScenarioCase) -> None:
    run_lifecycle("cache", case)


def test_all_principals_have_distinct_keys(scopes: dict[Who, IdentityScope]) -> None:
    from neurosphere_api.authz import scope_cache_key

    keys = {scope_cache_key(s, namespace="catalog") for s in scopes.values()}
    assert len(keys) == len(scopes) == 20
