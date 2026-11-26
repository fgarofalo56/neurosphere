"""``required_approval`` over catalog agent versions."""

from __future__ import annotations

from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.governance.policy.rules import RequiredApprovalEvaluator

from .rules_helpers import agent, agent_version, context, only_rule, policy, seed, version_id

NEEDS_APPROVAL = {"entity_types": ["agent_version"], "block_activation": True}


async def _world() -> InMemoryCatalogRepository:
    repo = InMemoryCatalogRepository()
    await seed(
        repo,
        agent("bot"),
        agent_version("bot-v1", "bot", state="approved"),
        agent_version("bot-v2", "bot", state="pending"),
        agent_version("bot-v3", "bot"),
    )
    return repo


async def test_unapproved_versions_are_findings_with_their_state() -> None:
    repo = await _world()
    definition = policy("required_approval", NEEDS_APPROVAL)

    outcome = await RequiredApprovalEvaluator(repo).evaluate(
        context("a"), definition, only_rule(definition)
    )

    assert not outcome.truncated
    assert [(f.subject_id, f.categories) for f in outcome.findings] == [
        (version_id("bot-v2"), ("pending",)),
        (version_id("bot-v3"), ("none",)),
    ]


async def test_approved_version_is_clean() -> None:
    repo = await _world()
    definition = policy("required_approval", NEEDS_APPROVAL, entity_ids=[version_id("bot-v1")])

    outcome = await RequiredApprovalEvaluator(repo).evaluate(
        context("a"), definition, only_rule(definition)
    )

    assert outcome.findings == ()


async def test_subject_budget_truncates() -> None:
    repo = await _world()
    definition = policy("required_approval", NEEDS_APPROVAL)

    outcome = await RequiredApprovalEvaluator(repo).evaluate(
        context("a", max_subjects=1), definition, only_rule(definition)
    )

    assert outcome.truncated
    assert outcome.reason == "subject_budget"
