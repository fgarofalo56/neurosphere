"""AgentMatcher service level tests with in-memory twins and counting fakes (PRP-72 item 3)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from neurosphere_contracts.recommendations.v1.agent_match_response import AgentMatchResponse
from neurosphere_core.errors import ForbiddenError, InvalidSchemaError, NotFoundError
from neurosphere_core.recommendations.matching import (
    AgentMatcher,
    AgentMatchReader,
    MatchSettings,
)
from neurosphere_core.recommendations.matching.feedback import (
    CandidateNotInMatchError,
    MatchNotFoundError,
)
from neurosphere_core.scope import IdentityScope

from .match_helpers import (
    FakeSubjects,
    World,
    agent_id,
    dom,
    make_agent,
    make_edge,
    make_feedback,
    make_point,
    make_request,
    make_scope,
    make_tool,
    tool_id,
    u,
)

TASK = "summarize support ticket"


async def _base_world(subjects: FakeSubjects | None = None) -> World:
    entities = [
        make_agent(
            "summarizer",
            "a",
            description="summarize support ticket conversations",
            tags=["support"],
            capabilities=["text.summarize"],
        ),
        make_agent("triage", "a", description="route support ticket queue", tags=["support"]),
        make_agent("billing", "a", description="invoice reconciliation helper"),
        make_agent("ticketbot", "b", description="summarize ticket backlog", tags=["support"]),
    ]
    return await World(entities, subjects=subjects).seed()


def _by_id(response: AgentMatchResponse) -> dict[str, dict[str, float | None]]:
    return {
        u(c.entity_id): {u(s.signal): s.contribution for s in c.signals}
        for c in response.candidates
    }


async def test_ranked_best_first_and_contributions_sum_to_score() -> None:
    world = await _base_world()
    scope = make_scope(["a", "b"])
    response = await world.matcher.match(scope, dom("a"), make_request(TASK, limit=3))

    assert 1 <= len(response.candidates) <= 3
    scores = [c.score for c in response.candidates]
    assert scores == sorted(scores, reverse=True)
    assert [c.rank for c in response.candidates] == list(range(1, len(scores) + 1))
    assert u(response.domain_id) == dom("a")
    assert u(response.ranker.ranker_id) == "weighted-signals"
    for cand in response.candidates:
        assert 0.0 <= cand.score <= 1.0
        assert len(cand.signals) == 8
        assert abs(sum(s.contribution for s in cand.signals) - cand.score) < 1e-9
    assert agent_id("billing") not in {u(c.entity_id) for c in response.candidates[:1]}


async def test_satisfies_the_reader_port() -> None:
    world = await _base_world()
    reader: AgentMatchReader = world.matcher
    response = await reader.match(make_scope(["a"]), dom("a"), make_request(TASK))
    assert response.candidates


async def test_tags_and_capabilities_are_reported_as_matched() -> None:
    world = await _base_world()
    response = await world.matcher.match(
        make_scope(["a"]),
        dom("a"),
        make_request(TASK, required_capabilities=["text.summarize"], preferred_tags=["support"]),
    )
    top = response.candidates[0]
    assert u(top.entity_id) == agent_id("summarizer")
    assert [u(c) for c in top.matched_capabilities] == ["text.summarize"]
    assert [u(t) for t in top.matched_tags] == ["support"]


async def test_cold_start_unobserved_telemetry_and_lower_confidence() -> None:
    entities = [
        make_agent("alpha", "a", description="summarize support ticket"),
        make_agent("bravo", "a", description="summarize support ticket"),
    ]
    subjects = FakeSubjects([make_point(agent_id("alpha"), "a", error_rate=None)])
    world = await World(entities, subjects=subjects).seed()
    result = await world.matcher.match_detailed(make_scope(["a"]), dom("a"), make_request(TASK))

    alpha, bravo = agent_id("alpha"), agent_id("bravo")
    assert result.cold_start == {alpha: False, bravo: True}
    assert result.confidence[alpha] > result.confidence[bravo]
    signals = {
        u(c.entity_id): {u(s.signal): s for s in c.signals} for c in result.response.candidates
    }
    # unknown error rate is unobserved, never 0
    assert signals[alpha]["historical_success"].value is None
    assert signals[alpha]["usage"].value is not None
    for name in ("historical_success", "latency", "usage"):
        assert signals[bravo][name].value is None
        assert signals[bravo][name].weight == 0.0
        assert signals[bravo][name].detail_code is not None
        assert u(signals[bravo][name].detail_code) == "no_telemetry"
    assert result.response.cold_start is False


async def test_all_cold_response_flags_cold_start_and_names_unavailable_signals() -> None:
    world = await _base_world(subjects=FakeSubjects())
    response = await world.matcher.match(make_scope(["a"]), dom("a"), make_request(TASK))
    assert response.cold_start is True
    unavailable = {u(s) for s in response.signals_unavailable}
    assert {"historical_success", "latency", "usage"} <= unavailable
    # signals the request never asked for are not "unavailable"
    assert "capability_match" not in unavailable
    assert "tag_match" not in unavailable
    assert "graph_proximity" not in unavailable


async def test_proximity_carries_the_relationship_path() -> None:
    entities = [
        make_agent("anchor", "a", description="payroll batch"),
        make_agent("near", "a", description="summarize support ticket"),
        make_agent("far", "a", description="summarize support ticket helper"),
        make_agent("mid", "a", description="payroll"),
    ]
    edges = [
        make_edge("anchor-near", "anchor", "near", "a"),
        make_edge("anchor-mid", "anchor", "mid", "a"),
        make_edge("mid-far", "mid", "far", "a"),
    ]
    world = await World(entities, edges=edges).seed()
    response = await world.matcher.match(
        make_scope(["a"]),
        dom("a"),
        make_request(TASK, context_entity_ids=[agent_id("anchor")], max_graph_depth=2),
    )
    cands = {u(c.entity_id): c for c in response.candidates}
    near = {u(s.signal): s for s in cands[agent_id("near")].signals}["graph_proximity"]
    far = {u(s.signal): s for s in cands[agent_id("far")].signals}["graph_proximity"]
    assert near.value is not None and u(near.value) == 1.0
    assert near.detail_code is not None and u(near.detail_code) == "hops_1"
    assert far.value is not None and u(far.value) == 0.5
    assert far.detail_code is not None and u(far.detail_code) == "hops_2"
    rel = cands[agent_id("near")].relations
    assert [(u(r.relation_type), u(r.entity_id), r.direction) for r in rel] == [
        ("invokes", agent_id("anchor"), "incoming")
    ]
    assert world.graph.walks == [agent_id("anchor")]

    # depth 1 cuts the two hop candidate off
    shallow = await world.matcher.match(
        make_scope(["a"]),
        dom("a"),
        make_request(TASK, context_entity_ids=[agent_id("anchor")], max_graph_depth=1),
    )
    far_s = {u(c.entity_id): c for c in shallow.candidates}[agent_id("far")]
    prox = {u(s.signal): s for s in far_s.signals}["graph_proximity"]
    assert prox.value is not None and u(prox.value) == 0.0


async def test_bounded_backend_calls() -> None:
    entities = [make_agent(f"w{i}", "a" if i % 2 else "b", description=TASK) for i in range(8)]
    entities += [make_agent("anc1", "a"), make_agent("anc2", "a"), make_agent("anc3", "b")]
    subjects = FakeSubjects([make_point(agent_id("w1"), "a")])
    world = await World(entities, subjects=subjects).seed()
    anchors = [agent_id("anc1"), agent_id("anc2"), agent_id("anc3")]
    await world.matcher.match(
        make_scope(["a", "b"]),
        dom("a"),
        make_request(TASK, context_entity_ids=anchors, limit=5),
    )
    assert len(world.search.requests) == 1
    assert sorted(world.graph.walks) == sorted(anchors)  # one walk per context id
    assert sorted(d for d, _ in subjects.reads) == [dom("a"), dom("b")]  # one read per domain
    request = world.search.requests[0]
    assert request.budget.limit <= 1000 and request.budget.max_depth == 0
    assert request.filters.entities == ["agent"]


async def test_telemetry_domain_cap_sets_partial() -> None:
    domains = [f"d{i:02d}" for i in range(22)]
    entities = [make_agent(f"x{i:02d}", d, description=TASK) for i, d in enumerate(domains)]
    subjects = FakeSubjects()
    world = await World(entities, subjects=subjects).seed()
    response = await world.matcher.match(
        make_scope(domains), dom("d00"), make_request(TASK, limit=50)
    )
    assert len(subjects.reads) == 20
    assert len({d for d, _ in subjects.reads}) == 20
    assert response.truncated is True
    assert response.partial_reason == "limit"
    assert len(response.candidates) == 22


async def test_reader_failure_degrades_telemetry_with_reason_code() -> None:
    subjects = FakeSubjects(fail=RuntimeError("boom"))
    world = await _base_world(subjects=subjects)
    response = await world.matcher.match(make_scope(["a"]), dom("a"), make_request(TASK))
    assert response.candidates
    assert response.cold_start is True
    for cand in response.candidates:
        sig = {u(s.signal): s for s in cand.signals}
        for name in ("historical_success", "latency", "usage"):
            assert sig[name].value is None
            assert sig[name].detail_code is not None
            assert u(sig[name].detail_code) == "telemetry_read_failed"
    assert {"historical_success", "latency", "usage"} <= {
        u(s) for s in response.signals_unavailable
    }


async def test_missing_reader_degrades_telemetry_with_reason_code() -> None:
    world = await _base_world()  # no subject reader composed
    response = await world.matcher.match(make_scope(["a"]), dom("a"), make_request(TASK))
    sig = {u(s.signal): s for s in response.candidates[0].signals}
    assert sig["usage"].value is None
    assert sig["usage"].detail_code is not None
    assert u(sig["usage"].detail_code) == "telemetry_reader_missing"


async def test_tools_are_candidates_with_unobserved_telemetry() -> None:
    entities = [
        make_agent("helper", "a", description=TASK),
        make_tool("lookup", "a", tags=["summarize", "support", "ticket"]),
    ]
    subjects = FakeSubjects([make_point(agent_id("helper"), "a")])
    world = await World(entities, subjects=subjects).seed()
    result = await world.matcher.match_detailed(
        make_scope(["a"]), dom("a"), make_request(TASK, candidate_types=["agent", "tool"])
    )
    types = {u(c.entity_id): c.entity_type for c in result.response.candidates}
    assert types == {agent_id("helper"): "agent", tool_id("lookup"): "tool"}
    assert result.cold_start[tool_id("lookup")] is True
    assert result.cold_start[agent_id("helper")] is False
    tool = next(c for c in result.response.candidates if c.entity_type == "tool")
    usage = {u(s.signal): s for s in tool.signals}["usage"]
    assert usage.value is None and usage.detail_code is not None
    assert u(usage.detail_code) == "tool_has_no_aggregates"
    assert subjects.reads == [(dom("a"), 1)]  # the tool was never sent to the aggregate reader
    assert world.search.requests[0].filters.entities == ["agent", "tool"]

    agents_only = await world.matcher.match(make_scope(["a"]), dom("a"), make_request(TASK))
    assert {c.entity_type for c in agents_only.candidates} == {"agent"}


async def test_candidate_cap_and_limit_set_partial_reason() -> None:
    entities = [make_agent(f"c{i}", "a", description=TASK) for i in range(5)]
    world = await World(entities, settings=MatchSettings(candidate_cap=2)).seed()
    response = await world.matcher.match(make_scope(["a"]), dom("a"), make_request(TASK))
    assert len(response.candidates) == 2
    assert response.truncated is True and response.partial_reason == "limit"


async def test_time_budget_exhaustion_sets_timeout_partial() -> None:
    world = await _base_world(subjects=FakeSubjects())
    ticks = iter(range(1000))
    matcher = AgentMatcher(
        world.search,
        world.graph,
        world.store,
        subjects=world.subjects,
        monotonic=lambda: float(next(ticks)),  # every read advances one second
        time_budget_ms=1500,
    )
    response = await matcher.match(make_scope(["a"]), dom("a"), make_request(TASK))
    assert response.truncated is True and response.partial_reason == "timeout_ms"
    assert response.candidates  # degraded, not failed


async def test_environment_filter_and_limit() -> None:
    entities = [
        make_agent("p1", "a", description=TASK, environment="production"),
        make_agent("s1", "a", description=TASK, environment="staging"),
    ]
    world = await World(entities).seed()
    prod = await world.matcher.match(
        make_scope(["a"]), dom("a"), make_request(TASK, environment="production")
    )
    assert [u(c.entity_id) for c in prod.candidates] == [agent_id("p1")]
    one = await world.matcher.match(make_scope(["a"]), dom("a"), make_request(TASK, limit=1))
    assert len(one.candidates) == 1


async def test_domain_outside_scope_is_refused() -> None:
    world = await _base_world()
    with pytest.raises(ForbiddenError):
        await world.matcher.match(make_scope(["a"]), dom("b"), make_request(TASK))


async def test_no_matching_text_returns_empty_and_records_nothing() -> None:
    world = await _base_world()
    response = await world.matcher.match(make_scope(["a"]), dom("a"), make_request("zzzzzz"))
    assert response.candidates == []
    assert response.cold_start is False
    assert world.store._matches == {}


# --------------------------------------------------------------------------- feedback


async def _principal_match(world: World, pseudonym: str, task: str = TASK) -> AgentMatchResponse:
    return await world.matcher.match(
        make_scope(["a"], pseudonym=pseudonym), dom("a"), make_request(task)
    )


def _prior(response: AgentMatchResponse, entity: str) -> tuple[float | None, float, str]:
    cand = next(c for c in response.candidates if u(c.entity_id) == entity)
    sig = {u(s.signal): s for s in cand.signals}["feedback_prior"]
    assert sig.detail_code is not None
    return (None if sig.value is None else u(sig.value)), sig.contribution, u(sig.detail_code)


def _score(response: AgentMatchResponse, entity: str) -> float:
    return next(c.score for c in response.candidates if u(c.entity_id) == entity)


async def test_feedback_below_min_principals_does_not_move_ranking() -> None:
    world = await _base_world()
    target = agent_id("triage")
    before = await _principal_match(world, "p-observer")
    for pseudonym in ("p-1", "p-2"):  # two principals: still below the minimum of three
        shown = await _principal_match(world, pseudonym)
        await world.matcher.record_feedback(
            make_scope(["a"], pseudonym=pseudonym),
            dom("a"),
            make_feedback(u(shown.match_id), target, "accepted"),
        )
    after = await _principal_match(world, "p-observer")
    value, contribution, detail = _prior(after, target)
    assert (value, contribution, detail) == (None, 0.0, "feedback_insufficient_evidence")
    assert [u(c.entity_id) for c in after.candidates] == [u(c.entity_id) for c in before.candidates]
    assert _score(after, target) == pytest.approx(_score(before, target))


async def test_feedback_from_three_principals_moves_score_by_a_bounded_visible_amount() -> None:
    world = await _base_world()
    liked, disliked = agent_id("triage"), agent_id("summarizer")
    before = await _principal_match(world, "p-observer")
    for pseudonym in ("p-1", "p-2", "p-3"):
        shown = await _principal_match(world, pseudonym)
        scope = make_scope(["a"], pseudonym=pseudonym)
        await world.matcher.record_feedback(
            scope, dom("a"), make_feedback(u(shown.match_id), liked, "accepted")
        )
        await world.matcher.record_feedback(
            scope,
            dom("a"),
            make_feedback(u(shown.match_id), disliked, "rejected", "poor_quality"),
        )
    after = await _principal_match(world, "p-observer")

    up_value, up, up_detail = _prior(after, liked)
    down_value, down, down_detail = _prior(after, disliked)
    assert up_detail == "feedback_positive" and down_detail == "feedback_negative"
    assert up_value is not None and up_value > 0.5
    assert down_value is not None and down_value < 0.5
    assert 0.0 < up <= 0.15 and -0.15 <= down < 0.0
    assert _score(after, liked) - _score(before, liked) == pytest.approx(up)
    assert _score(after, disliked) - _score(before, disliked) == pytest.approx(down)
    for cand in after.candidates:
        assert abs(sum(s.contribution for s in cand.signals) - cand.score) < 1e-9

    # a similar (not identical) task still benefits: token Jaccard >= 0.5
    similar = await _principal_match(world, "p-observer", "summarize support ticket queue")
    assert _prior(similar, liked)[2] == "feedback_positive"
    # a different task does not inherit it
    other = await _principal_match(world, "p-observer", "route ticket queue")
    assert _prior(other, liked)[2] == "feedback_insufficient_evidence"


async def test_feedback_prior_applies_to_a_cross_domain_candidate() -> None:
    # the only candidate lives in domain b; every match goes through domain a
    # (a stronger domain-b rival keeps the target's base score below 1.0, so the prior is not
    # clipped away)
    world = await World(
        [
            make_agent(
                "summarizer",
                "b",
                description="summarize support ticket conversations",
                tags=["support"],
                capabilities=["text.summarize"],
            ),
            make_agent("ticketbot", "b", description="ticket backlog"),
        ]
    ).seed()
    target = agent_id("ticketbot")

    def scope_for(pseudonym: str) -> IdentityScope:
        return make_scope(["a", "b"], pseudonym=pseudonym)

    before = await world.matcher.match(scope_for("p-observer"), dom("a"), make_request(TASK))
    assert target in {u(c.entity_id) for c in before.candidates}
    for pseudonym in ("p-1", "p-2", "p-3"):
        shown = await world.matcher.match(scope_for(pseudonym), dom("a"), make_request(TASK))
        await world.matcher.record_feedback(
            scope_for(pseudonym), dom("a"), make_feedback(u(shown.match_id), target, "accepted")
        )
    after = await world.matcher.match(scope_for("p-observer"), dom("a"), make_request(TASK))
    value, contribution, detail = _prior(after, target)
    assert detail == "feedback_positive"
    assert value is not None and value > 0.5
    assert 0.0 < contribution <= 0.15
    assert _score(after, target) - _score(before, target) == pytest.approx(contribution)


async def test_one_principal_cannot_move_a_ranking_and_decisions_replace() -> None:
    world = await _base_world()
    target = agent_id("triage")
    scope = make_scope(["a"], pseudonym="p-solo")
    shown = await world.matcher.match(scope, dom("a"), make_request(TASK))
    await world.matcher.record_feedback(
        scope, dom("a"), make_feedback(u(shown.match_id), target, "rejected")
    )
    await world.matcher.record_feedback(
        scope, dom("a"), make_feedback(u(shown.match_id), target, "accepted")
    )
    assert len(world.store._feedback) == 1  # one decision per (principal, match, candidate)
    stored = next(iter(world.store._feedback.values()))
    assert stored.decision == "accepted"
    again = await world.matcher.match(scope, dom("a"), make_request(TASK))
    assert _prior(again, target)[1] == 0.0


async def test_feedback_for_unseen_match_or_candidate_is_refused() -> None:
    world = await _base_world()
    scope = make_scope(["a"], pseudonym="p-1")
    shown = await world.matcher.match(scope, dom("a"), make_request(TASK))
    shown_ids = {u(c.entity_id) for c in shown.candidates}
    unseen = agent_id("billing")
    assert unseen not in shown_ids
    with pytest.raises(CandidateNotInMatchError) as not_in:
        await world.matcher.record_feedback(
            scope, dom("a"), make_feedback(u(shown.match_id), unseen, "accepted")
        )
    assert isinstance(not_in.value, InvalidSchemaError)
    with pytest.raises(MatchNotFoundError) as unknown:
        await world.matcher.record_feedback(
            scope, dom("a"), make_feedback("m-unknown", next(iter(shown_ids)), "accepted")
        )
    assert isinstance(unknown.value, NotFoundError)
    other = make_scope(["a"], pseudonym="p-2")  # someone else's match
    with pytest.raises(MatchNotFoundError):
        await world.matcher.record_feedback(
            other, dom("a"), make_feedback(u(shown.match_id), next(iter(shown_ids)), "accepted")
        )
    with pytest.raises(ForbiddenError):
        await world.matcher.record_feedback(
            make_scope(["b"]), dom("a"), make_feedback(u(shown.match_id), unseen, "accepted")
        )


async def test_metrics_rate_is_none_without_feedback_then_counts() -> None:
    world = await _base_world()
    scope = make_scope(["a"], pseudonym="p-1")
    since, until = datetime.now(UTC) - timedelta(hours=1), datetime.now(UTC) + timedelta(hours=1)
    empty = await world.matcher.metrics(scope, dom("a"), since, until)
    assert (empty.matches, empty.accepts, empty.rejects, empty.acceptance_rate) == (0, 0, 0, None)

    shown = await world.matcher.match(scope, dom("a"), make_request(TASK))
    await world.matcher.match(scope, dom("a"), make_request("billing"))
    no_feedback = await world.matcher.metrics(scope, dom("a"), since, until)
    assert no_feedback.matches >= 1
    assert no_feedback.acceptance_rate is None

    first, second = (u(c.entity_id) for c in shown.candidates[:2])
    await world.matcher.record_feedback(
        scope, dom("a"), make_feedback(u(shown.match_id), first, "accepted")
    )
    await world.matcher.record_feedback(
        scope, dom("a"), make_feedback(u(shown.match_id), second, "rejected")
    )
    metrics = await world.matcher.metrics(scope, dom("a"), since, until)
    assert (metrics.matches_with_feedback, metrics.accepts, metrics.rejects) == (1, 1, 1)
    assert metrics.acceptance_rate == 0.5
    with pytest.raises(ForbiddenError):
        await world.matcher.metrics(make_scope(["b"]), dom("a"), since, until)


# --------------------------------------------------------------------------- privacy


async def test_no_task_text_stored_or_logged(caplog: pytest.LogCaptureFixture) -> None:
    private_task = "reconcile zebra quarterly invoices"
    entities = [make_agent("recon", "a", description=private_task)]
    world = await World(
        entities, subjects=FakeSubjects(fail=RuntimeError("zebra pseudonym"))
    ).seed()
    scope = make_scope(["a"], pseudonym="p-private")
    with caplog.at_level(logging.DEBUG):
        response = await world.matcher.match(scope, dom("a"), make_request(private_task))
        await world.matcher.record_feedback(
            scope, dom("a"), make_feedback(u(response.match_id), agent_id("recon"), "accepted")
        )
    stored = repr(world.store._matches) + repr(world.store._feedback)
    assert private_task not in stored
    assert private_task not in json.dumps(response.model_dump(mode="json"))
    (match,) = world.store._matches.values()
    assert match.task_tokens == ("reconcile", "zebra", "quarterly", "invoices")
    assert len(match.task_tokens) <= 32
    assert match.principal == "p-private"
    for record in caplog.records:
        text = record.getMessage()
        assert "zebra" not in text and "reconcile" not in text and "p-private" not in text
    assert any("telemetry read failed" in r.getMessage() for r in caplog.records)
