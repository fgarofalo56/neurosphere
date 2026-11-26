"""``registration_required`` over agent subject points and agent versions."""

from __future__ import annotations

from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.governance.policy.rules import RegistrationRequiredEvaluator

from .rules_helpers import (
    FakeSubjects,
    agent,
    agent_id,
    agent_version,
    context,
    only_rule,
    policy,
    seed,
    subject_point,
    version_id,
)

AGENTS = {"entity_types": ["agent"], "grace_period_hours": 2}


async def _world() -> InMemoryCatalogRepository:
    repo = InMemoryCatalogRepository()
    await seed(
        repo,
        agent("known"),
        agent_version("known-v1", "known", state="approved"),
        agent_version("known-v2", "known"),
    )
    return repo


async def test_unregistered_agent_point_and_unsubmitted_version_are_findings() -> None:
    repo = await _world()
    subjects = FakeSubjects(
        [
            subject_point("agent", agent_id("known"), hours_ago=5),
            subject_point("agent", agent_id("shadow"), hours_ago=5),
        ]
    )
    definition = policy("registration_required", AGENTS)

    outcome = await RegistrationRequiredEvaluator(repo, subjects).evaluate(
        context("a"), definition, only_rule(definition)
    )

    assert not outcome.truncated
    by_subject = {f.subject_id: f for f in outcome.findings}
    assert set(by_subject) == {agent_id("shadow"), version_id("known-v2")}
    shadow = by_subject[agent_id("shadow")]
    assert shadow.evidence_class == "unregistered_agent"
    assert shadow.evidence[0].kind == "aggregate_window"
    assert shadow.counts == {"events": 10}


async def test_agent_seen_only_inside_the_grace_period_is_clean() -> None:
    repo = InMemoryCatalogRepository()
    subjects = FakeSubjects([subject_point("agent", agent_id("new"), hours_ago=1)])
    definition = policy("registration_required", AGENTS)

    outcome = await RegistrationRequiredEvaluator(repo, subjects).evaluate(
        context("a"), definition, only_rule(definition)
    )

    assert outcome.findings == ()
    assert not outcome.truncated


async def test_point_source_truncation_is_reported() -> None:
    repo = InMemoryCatalogRepository()
    subjects = FakeSubjects(
        [subject_point("agent", agent_id(f"shadow-{i}"), hours_ago=5) for i in range(3)]
    )
    definition = policy("registration_required", AGENTS)

    outcome = await RegistrationRequiredEvaluator(repo, subjects).evaluate(
        context("a", max_subjects=2), definition, only_rule(definition)
    )

    assert outcome.truncated
    assert outcome.reason == "subject_budget"
    assert len(outcome.findings) == 2
