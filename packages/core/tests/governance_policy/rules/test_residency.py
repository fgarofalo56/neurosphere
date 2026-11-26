"""``residency`` over grounding-source and model-deployment residency fields."""

from __future__ import annotations

from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.governance.policy.rules import ResidencyEvaluator
from neurosphere_core.governance.policy.rules.residency import residency_verdict

from .rules_helpers import StepClock, context, grounding_source, only_rule, policy, seed, source_id

EU_ONLY = {"allowed_geographies": ["eu_eea"], "allowed_regions": ["westeurope"]}


async def _world() -> InMemoryCatalogRepository:
    repo = InMemoryCatalogRepository()
    await seed(
        repo,
        grounding_source("eu", residency_region="westeurope", residency_geography="eu_eea"),
        grounding_source("us", residency_region="eastus", residency_geography="united_states"),
        grounding_source("unknown", residency_region=None, residency_geography=None),
    )
    return repo


async def test_asset_outside_allowed_set_is_a_finding() -> None:
    repo = await _world()
    definition = policy("residency", EU_ONLY)

    outcome = await ResidencyEvaluator(repo).evaluate(
        context("a"), definition, only_rule(definition)
    )

    assert not outcome.truncated
    assert [f.subject_id for f in outcome.findings] == [source_id("us")]
    assert outcome.findings[0].evidence[0].ref == source_id("us")


async def test_allowed_and_unassessed_assets_are_clean() -> None:
    repo = await _world()
    definition = policy(
        "residency", {"allowed_geographies": ["eu_eea", "united_states"], "allowed_regions": []}
    )

    outcome = await ResidencyEvaluator(repo).evaluate(
        context("a"), definition, only_rule(definition)
    )

    assert outcome.findings == ()


def test_verdict_null_is_unassessed_and_either_list_permits() -> None:
    regions, geos = frozenset({"westeurope"}), frozenset({"eu_eea"})
    assert residency_verdict(None, None, regions, geos) is None
    assert residency_verdict("WestEurope", None, regions, geos) is True
    assert residency_verdict("northeurope", "eu_eea", regions, geos) is True
    assert residency_verdict("eastus", None, regions, geos) is False


async def test_deadline_truncates() -> None:
    repo = await _world()
    definition = policy("residency", EU_ONLY)

    outcome = await ResidencyEvaluator(repo).evaluate(
        context("a", seconds=1.0, clock=StepClock(step=5.0)), definition, only_rule(definition)
    )

    assert outcome.truncated
    assert outcome.reason == "time_budget"
    assert outcome.findings == ()
