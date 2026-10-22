"""Citations (PRP-19 item 2): built from tool results, carry freshness, invented ones abstain."""

from __future__ import annotations

import pytest
from copilot_api_harness import (  # pyright: ignore[reportMissingImports]
    FINANCE,
    ScriptedAdapter,
    Step,
    call,
    cost_args,
    make_engine,
    make_scope,
    make_world,
    query_args,
    run_turn,
    say,
)
from neurosphere_api.copilot.models import AbstainEvent, CitationEvent
from neurosphere_core.scope import IdentityScope

FIN_AGENT = "commercial:contoso:foundry:agent:fin-1"


def analyst() -> IdentityScope:
    return make_scope([("analyst", [FINANCE])], [FINANCE])


def search_finance() -> Step:
    return call("search_catalog", {"query": query_args("agent", domain=FINANCE)})


async def test_every_citation_resolves_to_a_tool_result_and_carries_freshness() -> None:
    model = ScriptedAdapter(search_finance(), say("The finance agent is active [cite:r1]."))
    turn = await run_turn(make_engine(model, make_world()), analyst())

    assert turn.names[0] == "context"
    assert turn.terminal.name == "done"
    citations = [e.payload for e in turn.of("citation")]
    assert len(citations) == 1
    citation = citations[0]
    assert isinstance(citation, CitationEvent)
    assert citation.record_id == FIN_AGENT
    assert citation.freshness == "fresh" and citation.as_of == "2026-10-21T08:00:00Z"
    assert citation.kind == "agent" and citation.source == "catalog"
    # The marker became a numbered reference; the text never carries raw ids from the model.
    assert turn.text == "The finance agent is active [1]."

    # The cited id appears in the tool turn the model was actually given.
    tool_turns = [t for t in model.requests[-1].turns if t.role == "tool"]
    assert tool_turns and FIN_AGENT in tool_turns[0].content
    assert turn.persisted[0].citations[0].record_id == FIN_AGENT


@pytest.mark.parametrize(
    ("watermark", "expected"),
    [("2026-10-21T10:00:00Z", "fresh"), ("2026-10-01T00:00:00Z", "stale"), (None, "unknown")],
)
async def test_freshness_is_explicit_for_aggregates(watermark: str | None, expected: str) -> None:
    model = ScriptedAdapter(
        call("get_cost_summary", cost_args(domain=FINANCE)),
        say("Spend was steady [cite:r1]."),
    )
    turn = await run_turn(make_engine(model, make_world(watermark=watermark)), analyst())
    assert turn.terminal.name == "done"
    freshness = {
        e.payload.freshness for e in turn.of("citation") if isinstance(e.payload, CitationEvent)
    }
    assert freshness == {expected}
    if expected == "unknown":
        assert [e.payload.as_of for e in turn.of("citation")] == [None]  # type: ignore[union-attr]


async def test_invented_citation_abstains_and_nothing_is_released() -> None:
    model = ScriptedAdapter(search_finance(), say("It is excellent [cite:r99]."))
    turn = await run_turn(make_engine(model, make_world()), analyst())
    assert isinstance(turn.terminal.payload, AbstainEvent)
    assert turn.terminal.payload.reason_code == "unsupported_citation"
    assert not turn.of("token") and not turn.of("citation")
    assert turn.persisted[0].status == "abstain" and turn.persisted[0].text == ""


async def test_one_invented_citation_among_real_ones_still_abstains() -> None:
    model = ScriptedAdapter(
        search_finance(),
        say("Real [cite:r1] and fake [cite:r42]."),
    )
    turn = await run_turn(make_engine(model, make_world()), analyst())
    assert isinstance(turn.terminal.payload, AbstainEvent)
    assert turn.terminal.payload.reason_code == "unsupported_citation"


async def test_a_record_from_another_domain_cannot_be_cited() -> None:
    # The model only saw finance records; an operations agent id is invented to this turn.
    model = ScriptedAdapter(search_finance(), say("Operations too [cite:r2]."))
    turn = await run_turn(make_engine(model, make_world()), analyst())
    assert isinstance(turn.terminal.payload, AbstainEvent)
    assert turn.terminal.payload.reason_code == "unsupported_citation"


async def test_answer_without_any_citation_abstains() -> None:
    model = ScriptedAdapter(search_finance(), say("There is one agent."))
    turn = await run_turn(make_engine(model, make_world()), analyst())
    assert isinstance(turn.terminal.payload, AbstainEvent)
    assert turn.terminal.payload.reason_code == "uncited_answer"


async def test_a_full_record_id_typed_by_the_model_is_not_a_citation_handle() -> None:
    model = ScriptedAdapter(search_finance(), say(f"Real record [cite:{FIN_AGENT}]."))
    turn = await run_turn(make_engine(model, make_world()), analyst())
    assert isinstance(turn.terminal.payload, AbstainEvent)
    assert turn.terminal.payload.reason_code == "unsupported_citation"


async def test_the_model_is_given_a_handle_per_visible_record() -> None:
    model = ScriptedAdapter(search_finance(), say("Active [cite:r1]."))
    await run_turn(make_engine(model, make_world()), analyst())
    tool_turn = next(t for t in model.requests[1].turns if t.role == "tool")
    assert '"cite_as": "r1"' in tool_turn.content
