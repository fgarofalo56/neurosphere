"""``required_owner`` over catalog ``owned_by`` edges."""

from __future__ import annotations

from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.governance.policy.rules import RequiredOwnerEvaluator

from .rules_helpers import (
    agent,
    agent_id,
    context,
    only_rule,
    owned_by,
    owner,
    owner_id,
    policy,
    seed,
)

ONE_ACTIVE = {"min_owners": 1, "require_active_owner": True}


async def _world() -> InMemoryCatalogRepository:
    repo = InMemoryCatalogRepository()
    await seed(
        repo,
        agent("owned"),
        agent("orphan"),
        agent("stale-owner"),
        owner("team"),
        owner("gone", lifecycle="retired"),
        owned_by("o-owned", agent_id("owned"), owner_id("team")),
        owned_by("o-stale", agent_id("stale-owner"), owner_id("gone")),
    )
    return repo


async def test_entity_without_active_owner_is_a_finding() -> None:
    repo = await _world()
    definition = policy("required_owner", ONE_ACTIVE, entity_types=["agent"])

    outcome = await RequiredOwnerEvaluator(repo).evaluate(
        context("a"), definition, only_rule(definition)
    )

    assert not outcome.truncated
    by_subject = {f.subject_id: f for f in outcome.findings}
    assert set(by_subject) == {agent_id("orphan"), agent_id("stale-owner")}
    assert by_subject[agent_id("orphan")].counts == {"owners": 0, "min_owners": 1}
    stale_refs = {e.ref for e in by_subject[agent_id("stale-owner")].evidence}
    assert "commercial:acme:neurosphere:owned_by:o-stale" in stale_refs


async def test_inactive_owner_counts_when_not_required_active() -> None:
    repo = await _world()
    definition = policy(
        "required_owner",
        {"min_owners": 1, "require_active_owner": False},
        entity_ids=[agent_id("owned"), agent_id("stale-owner")],
    )

    outcome = await RequiredOwnerEvaluator(repo).evaluate(
        context("a"), definition, only_rule(definition)
    )

    assert outcome.findings == ()
    assert not outcome.truncated


async def test_subject_budget_truncates() -> None:
    repo = await _world()
    definition = policy("required_owner", ONE_ACTIVE, entity_types=["agent"])

    outcome = await RequiredOwnerEvaluator(repo).evaluate(
        context("a", max_subjects=2), definition, only_rule(definition)
    )

    assert outcome.truncated
    assert outcome.reason == "subject_budget"
    assert outcome.subjects_examined == 2
