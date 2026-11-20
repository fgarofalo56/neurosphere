"""``POST /api/v1/recommendations/domains/{domain}/match`` over HTTP (PRP-72 item 4)."""

from typing import Any

import pytest
from agent_match.match_helpers import (  # pyright: ignore[reportMissingImports]
    agent_id,
    dom,
    make_agent,
    make_edge,
    make_point,
    make_tool,
)
from match_support import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    CUSTOMER,
    FIN,
    NOBODY,
    OPS,
    ApiWorld,
    make_world,
)

HR = dom("hr", CUSTOMER)
SUMMARIZER = agent_id("ticket-summarizer", CUSTOMER)
PAYROLL = agent_id("payroll-bot", CUSTOMER)
OPS_AGENT = agent_id("ops-summarizer", CUSTOMER)
HR_AGENT = agent_id("hr-summarizer", CUSTOMER)


def _world(**kwargs: Any) -> ApiWorld:
    entities = [
        make_agent(
            "ticket-summarizer",
            "finance",
            description="summarize support ticket conversations",
            tags=["support", "summarize"],
            capabilities=["summarization"],
            ns=CUSTOMER,
        ),
        make_agent(
            "payroll-bot",
            "finance",
            description="run payroll batches",
            tags=["payroll"],
            ns=CUSTOMER,
        ),
        make_agent(
            "ops-summarizer",
            "operations",
            description="summarize support ticket conversations perfectly",
            tags=["support", "summarize"],
            ns=CUSTOMER,
        ),
        make_agent(
            "hr-summarizer",
            "hr",
            description="summarize support ticket conversations perfectly",
            tags=["support", "summarize"],
            ns=CUSTOMER,
        ),
        make_tool("ticket-tool", "finance", tags=["support"], ns=CUSTOMER),
    ]
    return make_world(entities, **kwargs)


def test_ranked_candidates_with_signals_summing_to_the_score() -> None:
    world = _world()
    response = world.match(ALICE)
    assert response.status_code == 200, response.text
    body = response.json()
    match = body["match"]
    assert match["domain_id"] == FIN
    candidates = match["candidates"]
    assert candidates[0]["entity_id"] == SUMMARIZER
    assert [c["rank"] for c in candidates] == list(range(1, len(candidates) + 1))
    scores = [c["score"] for c in candidates]
    assert scores == sorted(scores, reverse=True)
    for candidate in candidates:
        assert 0.0 <= candidate["score"] <= 1.0
        total = sum(s["contribution"] for s in candidate["signals"])
        assert total == pytest.approx(candidate["score"], abs=1e-9)
        assert {s["signal"] for s in candidate["signals"]} >= {"text_match", "tag_match"}
    assert [a["entity_id"] for a in body["assessments"]] == [c["entity_id"] for c in candidates]
    for assessment in body["assessments"]:
        assert 0.0 <= assessment["confidence"] <= 1.0
    assert "not a probability" in body["confidence_note"]


def test_a_candidate_without_telemetry_is_cold_start_and_less_confident() -> None:
    first = _world(points=[make_point(SUMMARIZER, "finance", ns=CUSTOMER)])
    observed = first.match(ALICE).json()
    assert observed["match"]["cold_start"] is False
    assessments = {a["entity_id"]: a for a in observed["assessments"]}
    assert assessments[SUMMARIZER]["cold_start"] is False
    cold = _world().match(ALICE).json()
    cold_summarizer = next(a for a in cold["assessments"] if a["entity_id"] == SUMMARIZER)
    assert cold_summarizer["cold_start"] is True
    assert cold_summarizer["confidence"] < assessments[SUMMARIZER]["confidence"]
    telemetry = next(
        s for s in cold["match"]["candidates"][0]["signals"] if s["signal"] == "historical_success"
    )
    assert telemetry["value"] is None  # unobserved, never 0


def test_out_of_scope_agents_never_appear() -> None:
    world = _world()
    bob_ids = {c["entity_id"] for c in world.match(BOB).json()["match"]["candidates"]}
    assert OPS_AGENT not in bob_ids and HR_AGENT not in bob_ids
    alice_ids = {c["entity_id"] for c in world.match(ALICE).json()["match"]["candidates"]}
    assert OPS_AGENT in alice_ids  # in scope for alice
    assert HR_AGENT not in alice_ids  # hr is nobody's in this world


def test_tools_are_candidates_only_when_requested() -> None:
    world = _world()
    default_types = {c["entity_type"] for c in world.match(ALICE).json()["match"]["candidates"]}
    assert default_types == {"agent"}
    both = world.match(ALICE, candidate_types=["agent", "tool"]).json()["match"]["candidates"]
    assert "tool" in {c["entity_type"] for c in both}


def test_limit_bounds_the_candidates() -> None:
    world = _world()
    candidates = world.match(ALICE, limit=1).json()["match"]["candidates"]
    assert len(candidates) == 1


def test_graph_proximity_names_the_relationship() -> None:
    entities = [
        make_agent("caller", "finance", description="coordinates work", ns=CUSTOMER),
        make_agent(
            "ticket-summarizer",
            "finance",
            description="summarize support ticket conversations",
            ns=CUSTOMER,
        ),
    ]
    edge = make_edge("e1", "caller", "ticket-summarizer", "finance", ns=CUSTOMER)
    world = make_world(entities, edges=[edge])
    response = world.match(ALICE, context_entity_ids=[agent_id("caller", CUSTOMER)])
    assert response.status_code == 200, response.text
    candidate = response.json()["match"]["candidates"][0]
    assert candidate["entity_id"] == SUMMARIZER
    proximity = next(s for s in candidate["signals"] if s["signal"] == "graph_proximity")
    assert proximity["value"] is not None
    assert candidate["relations"][0]["entity_id"] == agent_id("caller", CUSTOMER)


def test_context_ids_outside_scope_are_refused_not_ignored() -> None:
    world = _world()
    response = world.match(BOB, context_entity_ids=[OPS_AGENT])  # ops is outside bob's scope
    assert response.status_code == 403
    assert "context_entity_out_of_scope" in response.text
    missing = world.match(BOB, context_entity_ids=[agent_id("no-such-agent", CUSTOMER)])
    assert missing.status_code == 403


@pytest.mark.parametrize(
    "patch",
    [
        {"task_text": "x" * 2001},
        {"task_text": "ab"},
        {"context_entity_ids": [agent_id(f"a{i}", CUSTOMER) for i in range(21)]},
        {"limit": 51},
        {"candidate_types": ["workflow"]},
        {"domain_id": FIN},  # scope fields are rejected, never read from the body
    ],
)
def test_contract_bounds_are_422(patch: dict[str, object]) -> None:
    world = _world()
    body = {"schema_version": "1.0.0", "task_text": "summarize support ticket", **patch}
    assert world.post(ALICE, FIN, body).status_code == 422


def test_callers_without_data_read_on_the_domain_get_403_and_a_denial_record() -> None:
    world = _world()
    assert world.match(NOBODY).status_code == 403
    assert world.match(BOB, domain=OPS).status_code == 403
    assert world.match(BOB, domain=HR).status_code == 403
    assert world.post(None, FIN, {"schema_version": "1.0.0", "task_text": "abc"}).status_code == 401
    denied = world.denials.attempts
    assert len(denied) == 3
    assert {a.permission for a in denied} == {"data.read"}
    assert {a.domain_id for a in denied} == {FIN, OPS, HR}


def test_not_composed_is_503_and_unavailable_search_is_capability_unavailable() -> None:
    world = _world()
    world.h.app.state.agent_matcher = None
    response = world.match(ALICE)
    assert response.status_code == 503
    assert "recommendations_unconfigured" in response.text
    world.h.app.state.agent_matcher_unavailable = "search_unavailable"
    unavailable = world.match(ALICE)
    assert unavailable.status_code == 409
    assert unavailable.json()["code"] == "capability_unavailable"
    assert "search_unavailable" in unavailable.text


def test_task_text_is_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    world = _world()
    task = "reconcile the zorblax ledger"
    with caplog.at_level("DEBUG"):
        assert world.match(ALICE, task=task).status_code == 200
    assert "zorblax" not in caplog.text
