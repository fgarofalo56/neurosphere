"""``data_sensitivity_access`` on the in-memory catalog and the PRP-73 access engine."""

from __future__ import annotations

from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.governance.policy.rules import DataSensitivityAccessEvaluator

from .rules_helpers import (
    access_engine,
    agent,
    agent_id,
    agent_version,
    context,
    grounding_source,
    only_rule,
    policy,
    reads,
    seed,
    source_id,
    version_id,
)

PII_RULE = {
    "sensitivity_categories": ["pii"],
    "access": "read",
    "allowed_when": "agent_version_approved",
}


async def _world() -> InMemoryCatalogRepository:
    repo = InMemoryCatalogRepository()
    await seed(
        repo,
        agent("reader"),
        agent("approved", current_version_id=version_id("approved-v1")),
        agent_version("approved-v1", "approved", state="approved"),
        grounding_source("customers", sensitivity_categories=["pii"]),
        grounding_source("catalogue", sensitivity_categories=["financial"]),
        reads("r-reader-customers", agent_id("reader"), source_id("customers")),
        reads("r-approved-customers", agent_id("approved"), source_id("customers")),
        reads("r-reader-catalogue", agent_id("reader"), source_id("catalogue")),
    )
    return repo


async def test_unapproved_agent_reading_pii_is_one_finding_with_edge_and_asset() -> None:
    repo = await _world()
    evaluator = DataSensitivityAccessEvaluator(repo, access_engine(repo))
    definition = policy("data_sensitivity_access", PII_RULE)

    outcome = await evaluator.evaluate(context("a"), definition, only_rule(definition))

    assert not outcome.truncated
    assert len(outcome.findings) == 1
    finding = outcome.findings[0]
    assert finding.subject_id == agent_id("reader")
    assert finding.subject_type == "agent"
    assert {(e.kind, e.ref) for e in finding.evidence} == {
        ("relation", "commercial:acme:neurosphere:reads:r-reader-customers"),
        ("catalog_entity", source_id("customers")),
    }
    assert finding.categories == ("pii",)


async def test_approved_agent_and_non_matching_category_are_not_findings() -> None:
    repo = await _world()
    evaluator = DataSensitivityAccessEvaluator(repo, access_engine(repo))
    definition = policy("data_sensitivity_access", {**PII_RULE, "sensitivity_categories": ["phi"]})

    outcome = await evaluator.evaluate(context("a"), definition, only_rule(definition))

    assert outcome.findings == ()
    assert not outcome.truncated


async def test_exception_only_flags_even_the_approved_agent() -> None:
    repo = await _world()
    evaluator = DataSensitivityAccessEvaluator(repo, access_engine(repo))
    definition = policy("data_sensitivity_access", {**PII_RULE, "allowed_when": "exception_only"})

    outcome = await evaluator.evaluate(context("a"), definition, only_rule(definition))

    assert [f.subject_id for f in outcome.findings] == [agent_id("approved"), agent_id("reader")]


async def test_subject_budget_truncates() -> None:
    repo = await _world()
    evaluator = DataSensitivityAccessEvaluator(repo, access_engine(repo))
    definition = policy("data_sensitivity_access", {**PII_RULE, "allowed_when": "exception_only"})

    outcome = await evaluator.evaluate(
        context("a", max_subjects=1), definition, only_rule(definition)
    )

    # The engine's own bounds are lowered to the one subject left: it stops after one asset.
    assert outcome.truncated
    assert outcome.reason == "source_truncated"
    assert len(outcome.findings) <= 1
