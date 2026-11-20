"""Scope isolation of the matcher: out-of-scope data never appears and never influences a score."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from neurosphere_contracts.recommendations.v1.agent_match_response import AgentMatchResponse
from neurosphere_core.errors import ForbiddenError

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
    u,
)

TASK = "summarize support ticket"
EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
FAR_FUTURE = datetime(2100, 1, 1, tzinfo=UTC)


def _shape(response: AgentMatchResponse) -> list[tuple[str, float, list[tuple[str, float, float]]]]:
    return [
        (
            u(c.entity_id),
            c.score,
            [(u(s.signal), s.weight, s.contribution) for s in c.signals],
        )
        for c in response.candidates
    ]


async def test_out_of_scope_perfect_match_never_appears_or_influences_scores() -> None:
    mine = [
        make_agent("mine1", "a", description="summarize support ticket queue", tags=["support"]),
        make_agent("mine2", "a", description="support ticket triage helper"),
    ]
    foreign_perfect = make_agent(
        "perfect", "secret", description="summarize support ticket", tags=["support"]
    )
    foreign_customer = make_agent("other", "a", description="summarize support ticket", ns="globex")
    scope = make_scope(["a"])

    baseline = await World(mine).seed()
    polluted = await World([*mine, foreign_perfect, foreign_customer]).seed()
    req = make_request(TASK, preferred_tags=["support"])
    clean = await baseline.matcher.match(scope, dom("a"), req)
    mixed = await polluted.matcher.match(scope, dom("a"), req)

    ids = {u(c.entity_id) for c in mixed.candidates}
    assert agent_id("perfect") not in ids
    assert agent_id("other", "globex") not in ids
    assert ids == {agent_id("mine1"), agent_id("mine2")}
    # identical ranking, scores and every signal: foreign documents change nothing
    assert _shape(mixed) == _shape(clean)
    assert mixed.truncated is False and clean.truncated is False


async def test_foreign_domains_are_never_read_for_telemetry_or_feedback() -> None:
    entities = [
        make_agent("mine", "a", description=TASK),
        make_agent("theirs", "secret", description=TASK),
    ]
    subjects = FakeSubjects([make_point(agent_id("theirs"), "secret")])
    world = await World(entities, subjects=subjects).seed()
    response = await world.matcher.match(make_scope(["a"]), dom("a"), make_request(TASK))
    assert [u(c.entity_id) for c in response.candidates] == [agent_id("mine")]
    assert subjects.reads == [(dom("a"), 1)]
    assert all(dom("secret") not in str(read) for read in subjects.reads)


async def test_feedback_from_another_domain_cannot_influence_this_scope() -> None:
    entities = [
        make_agent("mine", "a", description=TASK),
        make_agent("theirs", "secret", description=TASK),
    ]
    world = await World(entities).seed()
    secret_scopes = [make_scope(["secret"], pseudonym=f"p-s{i}") for i in range(3)]
    match_ids: list[str] = []
    for scope in secret_scopes:
        shown = await world.matcher.match(scope, dom("secret"), make_request(TASK))
        match_ids.append(u(shown.match_id))
        await world.matcher.record_feedback(
            scope,
            dom("secret"),
            make_feedback(match_ids[-1], agent_id("theirs"), "accepted"),
        )
    # the secret domain's matches and decisions are invisible to a caller scoped to "a"
    mine = make_scope(["a"])
    response = await world.matcher.match(mine, dom("a"), make_request(TASK))
    assert [u(c.entity_id) for c in response.candidates] == [agent_id("mine")]
    metrics = await world.matcher.metrics(mine, dom("a"), since=EPOCH, until=FAR_FUTURE)
    assert metrics.accepts == 0 and metrics.acceptance_rate is None
    with pytest.raises(ForbiddenError):
        await world.matcher.record_feedback(
            mine, dom("secret"), make_feedback(match_ids[0], agent_id("theirs"), "rejected")
        )


async def test_context_entities_outside_scope_are_refused_not_ignored() -> None:
    entities = [
        make_agent("mine", "a", description=TASK),
        make_agent("theirs", "secret", description="payroll"),
    ]
    world = await World(entities).seed()
    scope = make_scope(["a"])
    with pytest.raises(ForbiddenError) as err:
        await world.matcher.match(
            scope,
            dom("a"),
            make_request(TASK, context_entity_ids=[agent_id("mine"), agent_id("theirs")]),
        )
    assert err.value.http_status == 403
    assert err.value.reason == "context_entity_out_of_scope"
    # an id that does not exist is indistinguishable from an out-of-scope one
    with pytest.raises(ForbiddenError):
        await world.matcher.match(
            scope, dom("a"), make_request(TASK, context_entity_ids=[agent_id("ghost")])
        )
    # refused before any search or graph walk ran
    assert world.search.requests == []
    assert world.graph.walks == []


async def test_path_domain_must_be_in_scope() -> None:
    world = await World([make_agent("mine", "a", description=TASK)]).seed()
    with pytest.raises(ForbiddenError) as err:
        await world.matcher.match(make_scope(["a"]), dom("secret"), make_request(TASK))
    assert err.value.reason == "domain_out_of_scope"
    assert world.search.requests == []


async def test_proximity_never_walks_into_a_foreign_domain() -> None:
    entities = [
        make_agent("anchor", "a", description="payroll"),
        make_agent("bridge", "secret", description="payroll"),
        make_agent("target", "a", description=TASK),
    ]
    edges = [
        make_edge("anchor-bridge", "anchor", "bridge", "secret"),
        make_edge("bridge-target", "bridge", "target", "secret"),
    ]
    world = await World(entities, edges=edges).seed()
    response = await world.matcher.match(
        make_scope(["a"]),
        dom("a"),
        make_request(TASK, context_entity_ids=[agent_id("anchor")]),
    )
    target = next(c for c in response.candidates if u(c.entity_id) == agent_id("target"))
    prox = {u(s.signal): s for s in target.signals}["graph_proximity"]
    assert prox.value is not None and u(prox.value) == 0.0
    assert prox.detail_code is not None and u(prox.detail_code) == "no_path"
    assert target.relations == []
