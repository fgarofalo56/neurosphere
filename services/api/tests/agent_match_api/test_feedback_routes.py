"""Feedback and metrics routes over HTTP (PRP-72 item 4)."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from agent_match.match_helpers import agent_id, make_agent  # pyright: ignore[reportMissingImports]
from match_support import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    CAROL,
    CUSTOMER,
    FIN,
    NOBODY,
    OPS,
    ApiWorld,
    make_world,
)
from neurosphere_core.audit.chains import domain_audit_chain_id

FIRST = agent_id("alpha-summarizer", CUSTOMER)
SECOND = agent_id("beta-summarizer", CUSTOMER)
TASK = "summarize support ticket"


def _world() -> ApiWorld:
    # Two agents that match the task equally well: only feedback can separate them.
    return make_world(
        [
            make_agent(
                "alpha-summarizer",
                "finance",
                description="summarize support ticket",
                tags=["support"],
                ns=CUSTOMER,
            ),
            make_agent(
                "beta-summarizer",
                "finance",
                description="summarize support ticket",
                tags=["support"],
                ns=CUSTOMER,
            ),
        ]
    )


def _match(world: ApiWorld, who: str) -> dict[str, Any]:
    # A tag nobody carries keeps the score below 1, so a feedback prior has room to move it.
    response = world.match(who, task=TASK, preferred_tags=["support", "billing"])
    assert response.status_code == 200, response.text
    return response.json()["match"]


def _scores(match: dict[str, Any]) -> dict[str, float]:
    return {c["entity_id"]: c["score"] for c in match["candidates"]}


def _metrics(world: ApiWorld, who: str = ALICE, **params: Any) -> dict[str, Any]:
    response = world.get(who, FIN, "/metrics", **params)
    assert response.status_code == 200, response.text
    return response.json()


def test_feedback_is_accepted_once_per_principal_match_candidate_and_replaces() -> None:
    world = _world()
    match = _match(world, ALICE)
    first = world.feedback(ALICE, match["match_id"], FIRST, "accepted")
    assert first.status_code == 202, first.text
    assert first.json()["decision"] == "accepted"
    assert _metrics(world)["accepts"] == 1
    again = world.feedback(ALICE, match["match_id"], FIRST, "accepted")
    assert again.status_code == 202
    assert _metrics(world)["accepts"] == 1  # stored once, not twice
    replaced = world.feedback(ALICE, match["match_id"], FIRST, "rejected")
    assert replaced.status_code == 202
    stats = _metrics(world)
    assert (stats["accepts"], stats["rejects"]) == (0, 1)


def test_feedback_is_audited_before_and_after() -> None:
    world = _world()
    match = _match(world, ALICE)
    chain = domain_audit_chain_id(CUSTOMER, FIN)
    assert asyncio.run(world.audit.tail(chain)) is None
    assert world.feedback(ALICE, match["match_id"], FIRST, "accepted").status_code == 202
    tail = asyncio.run(world.audit.tail(chain))
    assert tail is not None
    first_sequence = tail.sequence
    # a refused write still leaves a before and an after (failed) record, and no stored change
    refused = world.feedback(ALICE, match["match_id"], agent_id("other", CUSTOMER), "rejected")
    assert refused.status_code == 422
    later = asyncio.run(world.audit.tail(chain))
    assert later is not None and later.sequence == first_sequence + 2
    assert asyncio.run(world.audit.verify(chain)).ok


def test_feedback_for_something_not_shown_is_refused() -> None:
    world = _world()
    match = _match(world, ALICE)
    not_in_match = world.feedback(ALICE, match["match_id"], agent_id("other", CUSTOMER), "accepted")
    assert not_in_match.status_code == 422
    assert "candidate_not_in_match" in not_in_match.text
    unknown = world.feedback(ALICE, "m-does-not-exist", FIRST, "accepted")
    assert unknown.status_code == 404
    assert "match_not_found" in unknown.text
    # a match another principal received is not the caller's to rate
    someone_elses = world.feedback(CAROL, match["match_id"], FIRST, "accepted")
    assert someone_elses.status_code == 404
    assert _metrics(world)["accepts"] == 0


def test_feedback_body_is_validated() -> None:
    world = _world()
    match = _match(world, ALICE)
    bad_decision = {
        "schema_version": "1.0.0",
        "match_id": match["match_id"],
        "entity_id": FIRST,
        "decision": "maybe",
    }
    assert world.post(ALICE, FIN, bad_decision, "/feedback").status_code == 422
    free_text = {**bad_decision, "decision": "accepted", "comment": "free text is not allowed"}
    assert world.post(ALICE, FIN, free_text, "/feedback").status_code == 422


def test_three_principals_move_a_repeated_task_by_at_most_the_bound() -> None:
    world = _world()
    before = _scores(_match(world, ALICE))
    assert before[FIRST] == pytest.approx(before[SECOND])
    for who in (ALICE, BOB):
        match = _match(world, who)
        assert world.feedback(who, match["match_id"], FIRST, "accepted").status_code == 202
        # two principals are not enough evidence: the ranking has not moved yet
        assert _scores(_match(world, ALICE)) == pytest.approx(before)
    carol = _match(world, CAROL)
    assert world.feedback(CAROL, carol["match_id"], FIRST, "accepted").status_code == 202
    after_match = _match(world, ALICE)
    after = _scores(after_match)
    assert after[FIRST] > before[FIRST]
    assert after[FIRST] - before[FIRST] <= 0.15 + 1e-9
    assert after_match["candidates"][0]["entity_id"] == FIRST
    prior = next(
        s for s in after_match["candidates"][0]["signals"] if s["signal"] == "feedback_prior"
    )
    assert prior["value"] is not None and prior["contribution"] > 0.0
    for candidate in after_match["candidates"]:  # contributions still sum to the score
        total = sum(s["contribution"] for s in candidate["signals"])
        assert total == pytest.approx(candidate["score"], abs=1e-9)


def test_metrics_rate_is_null_without_feedback_then_a_share() -> None:
    world = _world()
    empty = _metrics(world)
    assert (empty["matches"], empty["accepts"], empty["rejects"]) == (0, 0, 0)
    assert empty["acceptance_rate"] is None
    match = _match(world, ALICE)
    seen = _metrics(world)
    assert seen["matches"] == 1 and seen["matches_with_feedback"] == 0
    assert seen["acceptance_rate"] is None  # not 0: nothing was decided
    world.feedback(ALICE, match["match_id"], FIRST, "accepted")
    other = _match(world, BOB)
    world.feedback(BOB, other["match_id"], FIRST, "accepted")
    third = _match(world, CAROL)
    world.feedback(CAROL, third["match_id"], FIRST, "rejected")
    stats = _metrics(world)
    assert (stats["accepts"], stats["rejects"]) == (2, 1)
    assert stats["matches_with_feedback"] == 3
    assert stats["acceptance_rate"] == pytest.approx(2 / 3)
    assert stats["domain_id"] == FIN


def test_metrics_window_parameters() -> None:
    world = _world()
    _match(world, ALICE)
    now = datetime.now(UTC)
    past = _metrics(
        world,
        since=(now - timedelta(days=20)).isoformat(),
        until=(now - timedelta(days=10)).isoformat(),
    )
    assert past["matches"] == 0
    assert past["window_start"] < past["window_end"]
    inverted = world.get(ALICE, FIN, "/metrics", since=now.isoformat(), until=past["window_start"])
    assert inverted.status_code == 422
    assert "invalid_window" in inverted.text
    too_wide = world.get(
        ALICE, FIN, "/metrics", since=(now - timedelta(days=400)).isoformat(), until=now.isoformat()
    )
    assert too_wide.status_code == 422


def test_feedback_and_metrics_need_data_read_on_the_domain() -> None:
    world = _world()
    match = _match(world, ALICE)
    assert world.feedback(NOBODY, match["match_id"], FIRST, "accepted").status_code == 403
    assert world.feedback(BOB, match["match_id"], FIRST, "accepted", domain=OPS).status_code == 403
    assert world.get(BOB, OPS, "/metrics").status_code == 403
    assert world.get(NOBODY, FIN, "/metrics").status_code == 403
    assert world.get(None, FIN, "/metrics").status_code == 401
    assert [a.permission for a in world.denials.attempts] == ["data.read"] * 4
    assert _metrics(world)["accepts"] == 0


def test_feedback_without_audit_is_not_accepted() -> None:
    world = _world()
    match = _match(world, ALICE)
    world.h.app.state.audit_repository = None
    refused = world.feedback(ALICE, match["match_id"], FIRST, "accepted")
    assert refused.status_code == 503
    assert "audit_unconfigured" in refused.text
    assert _metrics(world)["accepts"] == 0
