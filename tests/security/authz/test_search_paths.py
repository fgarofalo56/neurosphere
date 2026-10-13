"""Search path: the AuthorizedSearch server-side filter is applied; callers cannot widen it."""

import pytest
from neurosphere_core.auth.scope import Role
from neurosphere_core.search import AuthorizedSearch, SearchFilters, SearchRequest
from neurosphere_core.search.fixture import FixtureSearchIndex, documents_from_catalog

from .cases import SEARCH_CASES, ScenarioCase, SearchCase, domain_docs, scenario_cases
from .executors import LIFECYCLE_SCENARIOS, run_lifecycle, run_search_case
from .world import SEARCH_BUDGET, Who, World, catalog_entities, run

PLAIN = [c for c in SEARCH_CASES if ".priv." not in c.id]
LIFECYCLE = [c for c in scenario_cases("search") if c.scenario in LIFECYCLE_SCENARIOS]


@pytest.mark.parametrize("case", PLAIN, ids=lambda c: c.id)
def test_search_case(ro_world: World, case: SearchCase) -> None:
    run_search_case(ro_world, case)


@pytest.mark.parametrize("case", LIFECYCLE, ids=lambda c: c.id)
def test_search_lifecycle(case: ScenarioCase) -> None:
    run_lifecycle("search", case)


def test_fixture_implements_the_authorized_search_protocol(ro_world: World) -> None:
    assert isinstance(ro_world.search_index, AuthorizedSearch)


def test_out_of_scope_documents_do_not_influence_ranking(ro_world: World) -> None:
    """Scope runs before ranking: a corpus holding only the caller's documents scores the same."""
    who = Who("contoso", "finance", Role.ANALYST)
    scope = ro_world[who.customer].scope(who)
    own = [
        d for d in documents_from_catalog(catalog_entities()) if d.id in domain_docs(who.domain_id)
    ]
    request = SearchRequest(term="triage assistant", budget=SEARCH_BUDGET)
    full = run(ro_world.search_index.search(scope.to_contract(), request))
    only_own = run(FixtureSearchIndex(own).search(scope.to_contract(), request))
    assert [(h.id, h.score) for h in full.hits] == [(h.id, h.score) for h in only_own.hits]
    assert {h.id for h in full.hits} <= domain_docs(who.domain_id)


def test_search_request_has_no_scope_or_customer_parameter() -> None:
    fields = set(SearchRequest.model_fields) | set(SearchFilters.model_fields)
    assert not fields & {"scope", "customer_id", "allowed_domains", "cloud", "principal"}
