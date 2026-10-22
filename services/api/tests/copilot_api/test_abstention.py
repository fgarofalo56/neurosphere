"""Abstention (PRP-19 item 2): no authorized evidence -> a first-class abstain with a reason."""

from __future__ import annotations

from copilot_api_harness import (  # pyright: ignore[reportMissingImports]
    FINANCE,
    OPERATIONS,
    ScriptedAdapter,
    Step,
    call,
    make_engine,
    make_scope,
    make_world,
    query_args,
    run_turn,
    say,
)
from neurosphere_api.copilot import CopilotSettings
from neurosphere_api.copilot.models import AbstainEvent
from neurosphere_core.scope import IdentityScope

FIN_AGENT = "commercial:contoso:foundry:agent:fin-1"


def analyst() -> IdentityScope:
    return make_scope([("analyst", [FINANCE])], [FINANCE])


def search(domain: str = FINANCE) -> Step:
    return call("search_catalog", {"query": query_args("agent", domain=domain)})


async def test_a_model_answer_with_no_tool_call_is_an_abstention() -> None:
    model = ScriptedAdapter(say("Finance spend is up 40% [cite:made-up]."))
    turn = await run_turn(make_engine(model, make_world()), analyst())
    assert turn.names == ["context", "abstain"]
    payload = turn.terminal.payload
    assert isinstance(payload, AbstainEvent)
    assert payload.reason_code == "no_authorized_evidence" and payload.reason
    assert not turn.of("token")


async def test_tools_that_return_nothing_abstain() -> None:
    model = ScriptedAdapter(search(), say("Nothing to report [cite:x]."))
    turn = await run_turn(make_engine(model, make_world(entities=[])), analyst())
    assert turn.terminal.name == "abstain"
    assert turn.terminal.payload.reason_code == "no_authorized_evidence"  # type: ignore[union-attr]
    assert [e.payload.status for e in turn.of("tool")] == ["started", "ok"]  # type: ignore[union-attr]


async def test_data_in_a_domain_outside_the_derived_scope_is_never_evidence() -> None:
    # The caller reads finance only. The operations agent exists but the tool never returns it.
    model = ScriptedAdapter(search(), say("Only finance [cite:r1]."))
    turn = await run_turn(make_engine(model, make_world()), analyst())
    assert turn.terminal.name == "done"
    tool_content = next(t.content for t in model.requests[-1].turns if t.role == "tool")
    assert "ops-1" not in tool_content and OPERATIONS not in tool_content


async def test_unconfigured_evidence_reader_abstains_instead_of_inventing() -> None:
    auditor = make_scope([("analyst", [FINANCE]), ("security_auditor", [FINANCE])], [FINANCE])
    model = ScriptedAdapter(
        call(
            "get_evidence",
            {
                "evidence_ids": ["ev-1"],
                "budget": {"timeout_ms": 1000, "limit": 10, "max_depth": 0},
            },
        ),
        say("The evidence shows a regression [cite:ev-1]."),
    )
    turn = await run_turn(make_engine(model, make_world()), auditor)
    assert turn.terminal.name == "abstain"
    assert turn.terminal.payload.reason_code == "no_authorized_evidence"  # type: ignore[union-attr]


async def test_endless_tool_calls_exhaust_the_budget_and_abstain() -> None:
    settings = CopilotSettings(max_tool_iterations=2)
    model = ScriptedAdapter(search())  # repeats forever
    world = make_world()
    turn = await run_turn(make_engine(model, world, settings=settings), analyst())
    assert turn.terminal.name == "abstain"
    assert turn.terminal.payload.reason_code == "tool_budget_exhausted"  # type: ignore[union-attr]
    assert len(model.requests) == 2


async def test_an_empty_answer_abstains() -> None:
    model = ScriptedAdapter(search(), say("   "))
    turn = await run_turn(make_engine(model, make_world()), analyst())
    assert turn.terminal.name == "abstain"
    assert turn.terminal.payload.reason_code == "empty_answer"  # type: ignore[union-attr]


async def test_abstained_turns_persist_no_answer_text() -> None:
    model = ScriptedAdapter(say("Confident but unsupported."))
    turn = await run_turn(make_engine(model, make_world()), analyst())
    outcome = turn.persisted[0]
    assert (outcome.status, outcome.text, outcome.citations) == ("abstain", "", ())
    assert outcome.reason_code == "no_authorized_evidence"
