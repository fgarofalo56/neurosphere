"""``model_allow_list`` over catalog ``uses_model`` edges and model subject points."""

from __future__ import annotations

from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.governance.policy.rules import ModelAllowListEvaluator, telemetry_model_id

from .rules_helpers import (
    FakeSubjects,
    agent,
    agent_id,
    context,
    deployment,
    deployment_id,
    only_rule,
    policy,
    seed,
    subject_point,
    uses_model,
)

ALLOW_GPT4O = {"allowed_models": [{"model_name": "gpt-4o", "model_version": None}]}


async def _world() -> InMemoryCatalogRepository:
    repo = InMemoryCatalogRepository()
    await seed(
        repo,
        agent("good"),
        agent("rogue"),
        deployment("gpt4o-prod", model="gpt-4o"),
        deployment("llama-prod", model="llama-3"),
        uses_model("u-good", agent_id("good"), deployment_id("gpt4o-prod")),
        uses_model("u-rogue", agent_id("rogue"), deployment_id("llama-prod")),
    )
    return repo


async def test_disallowed_deployment_and_model_point_are_findings() -> None:
    repo = await _world()
    subjects = FakeSubjects(
        [
            subject_point("model", "azure_openai/gpt-4o"),
            subject_point("model", "meta/llama-3"),
            subject_point("agent", agent_id("good")),
        ]
    )
    definition = policy("model_allow_list", ALLOW_GPT4O)

    outcome = await ModelAllowListEvaluator(repo, subjects).evaluate(
        context("a"), definition, only_rule(definition)
    )

    assert not outcome.truncated
    by_subject = {f.subject_id: f for f in outcome.findings}
    assert set(by_subject) == {
        agent_id("rogue"),
        telemetry_model_id("commercial", "acme", "model:meta/llama-3"),
    }
    rogue = by_subject[agent_id("rogue")]
    assert {(e.kind, e.ref) for e in rogue.evidence} == {
        ("relation", "commercial:acme:neurosphere:uses_model:u-rogue"),
        ("catalog_entity", deployment_id("llama-prod")),
    }
    point = by_subject[telemetry_model_id("commercial", "acme", "model:meta/llama-3")]
    assert point.subject_type == "model"
    assert point.evidence[0].kind == "aggregate_window"


async def test_everything_allowed_by_name_or_deployment_id_is_clean() -> None:
    repo = await _world()
    subjects = FakeSubjects([subject_point("model", "meta/llama-3")])
    definition = policy(
        "model_allow_list",
        {**ALLOW_GPT4O, "allowed_deployment_ids": [deployment_id("llama-prod")]},
    )

    outcome = await ModelAllowListEvaluator(repo, subjects).evaluate(
        context("a"), definition, only_rule(definition)
    )

    assert outcome.findings == ()
    assert not outcome.truncated


async def test_pinned_version_mismatch_is_a_finding() -> None:
    repo = await _world()
    definition = policy(
        "model_allow_list",
        {"allowed_models": [{"model_name": "gpt-4o", "model_version": "2099-01-01"}]},
    )

    outcome = await ModelAllowListEvaluator(repo, FakeSubjects()).evaluate(
        context("a"), definition, only_rule(definition)
    )

    assert {f.subject_id for f in outcome.findings} == {agent_id("good"), agent_id("rogue")}


async def test_subject_budget_truncates() -> None:
    repo = await _world()
    definition = policy("model_allow_list", ALLOW_GPT4O)

    outcome = await ModelAllowListEvaluator(repo, FakeSubjects()).evaluate(
        context("a", max_subjects=1), definition, only_rule(definition)
    )

    assert outcome.truncated
    assert outcome.reason == "subject_budget"
