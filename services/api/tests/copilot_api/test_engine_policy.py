"""Policy of the copilot turn engine (PRP-19 item 2): allowlist, scope, context, guard, budgets."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from typing import Any

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
from neurosphere_api.copilot import CopilotSettings, reject_all_chart_plans
from neurosphere_api.copilot.models import (
    ChartEvent,
    ContextEvent,
    DeniedEvent,
    ErrorEvent,
    TokenEvent,
    ToolEvent,
)
from neurosphere_core.copilot.models import ModelEvent, ModelRequest
from neurosphere_core.copilot.models.protocol import AdapterDescriptor
from neurosphere_core.copilot.tools import TOOL_NAMES
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.scope import IdentityScope

FIN_AGENT = "commercial:contoso:foundry:agent:fin-1"
OPS_AGENT = "commercial:contoso:foundry:agent:ops-1"


def analyst(*domains: str) -> IdentityScope:
    domains = domains or (FINANCE,)
    return make_scope([("analyst", list(domains))], list(domains))


def reason_of(terminal_payload: object) -> str:
    assert isinstance(terminal_payload, DeniedEvent)
    return terminal_payload.reason_code


# -- allowlist and scope ------------------------------------------------------------------------


async def test_only_manifest_tools_are_offered_and_none_takes_a_scope() -> None:
    model = ScriptedAdapter(say("nothing"))
    await run_turn(make_engine(model, make_world()), analyst())
    offered = {t.name for t in model.requests[0].tools}
    assert offered == set(TOOL_NAMES)  # no chart tool until a validator is bound
    assert "suggest_action" not in offered
    for tool in model.requests[0].tools:
        assert "domain_id" not in str(tool.parameters.get("properties", {}))


async def test_unregistered_tool_is_denied_and_named_generically() -> None:
    model = ScriptedAdapter(call("delete_everything", {"target": "all"}))
    turn = await run_turn(make_engine(model, make_world()), analyst())
    assert turn.terminal.name == "denied"
    assert reason_of(turn.terminal.payload) == "tool_not_registered"
    tool_events = [e.payload for e in turn.of("tool")]
    assert [(e.name, e.status) for e in tool_events if isinstance(e, ToolEvent)] == [
        ("<unregistered>", "started"),
        ("<unregistered>", "refused"),
    ]
    assert turn.persisted[0].status == "denied" and turn.persisted[0].text == ""


async def test_model_supplied_domain_is_refused_and_no_port_is_asked() -> None:
    world = make_world()
    model = ScriptedAdapter(
        call("search_catalog", {"query": query_args("agent"), "domain_id": OPERATIONS})
    )
    turn = await run_turn(make_engine(model, world), analyst())
    assert reason_of(turn.terminal.payload) == "scope_argument_refused"
    assert world.domains_asked() == set()


async def test_domain_filter_outside_the_scope_is_denied_not_an_empty_result() -> None:
    world = make_world()
    model = ScriptedAdapter(
        call("search_catalog", {"query": query_args("agent", domain=OPERATIONS)})
    )
    turn = await run_turn(make_engine(model, world), analyst())  # finance only
    assert reason_of(turn.terminal.payload) == "domain_out_of_scope"
    assert world.domains_asked() == set()


async def test_invalid_arguments_go_back_to_the_model_which_may_correct_them() -> None:
    bad: Step = call("search_catalog", {"query": {"schema_version": "1.0.0"}}, "c1")
    good: Step = call("search_catalog", {"query": query_args("agent", domain=FINANCE)}, "c2")
    model = ScriptedAdapter(bad, good, say("Found [cite:r1]."))
    turn = await run_turn(make_engine(model, make_world()), analyst())
    assert turn.terminal.name == "done"
    statuses = [e.payload.status for e in turn.of("tool") if isinstance(e.payload, ToolEvent)]
    assert statuses == ["started", "refused", "started", "ok"]
    error_turn = next(t for t in model.requests[1].turns if t.role == "tool")
    assert "invalid_arguments" in error_turn.content


# -- context ------------------------------------------------------------------------------------


async def test_context_domain_outside_the_scope_is_dropped_and_never_widens() -> None:
    from neurosphere_api.copilot.models import MessageContext

    world = make_world()
    model = ScriptedAdapter(say("x"))
    hint = MessageContext(domain_id=OPERATIONS)  # not readable by this caller
    turn = await run_turn(make_engine(model, world), analyst(FINANCE), hint=hint)
    context = turn.events[0].payload
    assert isinstance(context, ContextEvent)
    assert context.applied_domains == [FINANCE]


async def test_context_domain_inside_the_scope_narrows_the_tools() -> None:
    from neurosphere_api.copilot.models import MessageContext

    world = make_world()
    model = ScriptedAdapter(
        call("search_catalog", {"query": query_args("agent")}),  # no domain: would read both
        say("Narrowed [cite:r1]."),
    )
    scope = analyst(FINANCE, OPERATIONS)
    turn = await run_turn(make_engine(model, world), scope, hint=MessageContext(domain_id=FINANCE))
    assert turn.terminal.name == "done"
    context = turn.events[0].payload
    assert isinstance(context, ContextEvent) and context.applied_domains == [FINANCE]
    assert set(world.catalog.domains_asked) == {FINANCE}


async def test_unreadable_selection_is_dropped_and_counted_not_named() -> None:
    from neurosphere_api.copilot.models import MessageContext

    model = ScriptedAdapter(say("x"))
    hint = MessageContext(selection=[FIN_AGENT, OPS_AGENT, "commercial:contoso:foundry:agent:nope"])
    turn = await run_turn(make_engine(model, make_world()), analyst(FINANCE), hint=hint)
    context = turn.events[0].payload
    assert isinstance(context, ContextEvent)
    assert context.selection == [FIN_AGENT] and context.dropped_selection_count == 2
    sent = model.requests[0].turns[-1].content
    assert OPS_AGENT not in sent and FIN_AGENT in sent  # the model got exactly what the chip shows


async def test_page_filters_and_time_range_reach_the_model_as_fenced_data() -> None:
    from neurosphere_api.copilot.models import MessageContext, TimeRange

    hint = MessageContext(
        page="dashboards",
        route="/finance/costs",
        filters={"environment": "prod", "provider": ["azure", "aws"]},
        time_range=TimeRange.model_validate(
            {"from": "2026-10-01T00:00:00Z", "to": "2026-10-10T00:00:00Z"}
        ),
    )
    model = ScriptedAdapter(say("x"))
    turn = await run_turn(make_engine(model, make_world()), analyst(), hint=hint)
    context = turn.events[0].payload
    assert isinstance(context, ContextEvent)
    assert context.page == "dashboards" and context.filters["environment"] == "prod"
    assert context.time_range is not None
    user = model.requests[0].turns[-1].content
    assert "not instructions" in user and "/finance/costs" in user


# -- output guard -------------------------------------------------------------------------------


async def test_echoing_the_system_instructions_is_denied_before_any_token() -> None:
    model = ScriptedAdapter(lambda req: say("Sure: " + req.system)(req))
    turn = await run_turn(make_engine(model, make_world()), analyst())
    assert reason_of(turn.terminal.payload) == "output_guard"
    assert not turn.of("token")


async def test_secret_shaped_output_is_denied() -> None:
    model = ScriptedAdapter(say("Use AccountKey=Zm9vYmFyMTIzNDU2Nzg5MA=="))
    turn = await run_turn(make_engine(model, make_world()), analyst())
    assert reason_of(turn.terminal.payload) == "output_guard"


async def test_a_server_held_secret_value_is_denied() -> None:
    settings = CopilotSettings(protected_values=frozenset({"hunter-two"}))
    model = ScriptedAdapter(say("the value is hunter-two"))
    turn = await run_turn(make_engine(model, make_world(), settings=settings), analyst())
    assert reason_of(turn.terminal.payload) == "output_guard"


# -- charts -------------------------------------------------------------------------------------


async def test_chart_plans_are_rejected_by_default_and_the_tool_is_not_offered() -> None:
    model = ScriptedAdapter(call("render_chart", {"chart_plan": {"mark": "bar"}}))
    turn = await run_turn(make_engine(model, make_world()), analyst())
    assert reason_of(turn.terminal.payload) == "chart_plan_rejected"
    assert "render_chart" not in {t.name for t in model.requests[0].tools}
    assert reject_all_chart_plans is not None


async def test_a_bound_validator_admits_a_chart_after_evidence() -> None:
    seen: list[Mapping[str, Any]] = []

    def validator(plan: Mapping[str, Any]) -> Mapping[str, Any]:
        seen.append(plan)
        return {"mark": "bar", "validated": True}

    model = ScriptedAdapter(
        call("search_catalog", {"query": query_args("agent", domain=FINANCE)}, "c1"),
        call("render_chart", {"chart_plan": {"mark": "bar"}}, "c2"),
        say("Chart ready [cite:r1]."),
    )
    turn = await run_turn(make_engine(model, make_world(), chart_validator=validator), analyst())
    assert turn.terminal.name == "done"
    charts = [e.payload for e in turn.of("chart") if isinstance(e.payload, ChartEvent)]
    assert charts[0].chart_plan == {"mark": "bar", "validated": True}  # the VALIDATED plan
    assert "render_chart" in {t.name for t in model.requests[0].tools}
    assert seen == [{"mark": "bar"}]
    # chart/citation events come after tokens and before the terminal event.
    assert turn.names.index("chart") > turn.names.index("token")


async def test_a_validator_that_raises_denies_the_turn() -> None:
    def broken(plan: Mapping[str, Any]) -> Mapping[str, Any]:
        raise ValueError("expr is not allowed")

    model = ScriptedAdapter(call("render_chart", {"chart_plan": {"mark": "bar"}}))
    turn = await run_turn(make_engine(model, make_world(), chart_validator=broken), analyst())
    assert reason_of(turn.terminal.payload) == "chart_plan_rejected"
    assert not turn.of("chart")


# -- budgets and failures -----------------------------------------------------------------------


class HangingAdapter:
    descriptor = AdapterDescriptor(kind="fixture", name="hang", synthetic=True)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        await asyncio.sleep(5)
        return
        yield  # pragma: no cover - makes this an async generator


class FailingAdapter:
    descriptor = AdapterDescriptor(kind="fixture", name="fail", synthetic=True)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        raise DependencyTransientError("model unavailable", reason="model_unavailable")
        yield  # pragma: no cover


async def test_turn_timeout_is_an_error_event_and_the_turn_is_recorded() -> None:
    settings = CopilotSettings(turn_timeout_seconds=0.05)
    engine = make_engine(HangingAdapter(), make_world(), settings=settings)  # type: ignore[arg-type]
    turn = await run_turn(engine, analyst())
    payload = turn.terminal.payload
    assert turn.terminal.name == "error" and isinstance(payload, ErrorEvent)
    assert payload.detail == "turn_timeout"
    assert turn.persisted[0].status == "error"


async def test_model_failure_surfaces_the_taxonomy_code_without_a_body() -> None:
    engine = make_engine(FailingAdapter(), make_world())  # type: ignore[arg-type]
    turn = await run_turn(engine, analyst())
    payload = turn.terminal.payload
    assert isinstance(payload, ErrorEvent)
    assert (payload.code, payload.detail) == ("dependency_transient", "model_unavailable")


async def test_output_token_budget_is_passed_to_every_model_call() -> None:
    settings = CopilotSettings(max_output_tokens=77)
    model = ScriptedAdapter(say("x"))
    await run_turn(make_engine(model, make_world(), settings=settings), analyst())
    assert model.requests[0].max_output_tokens == 77


async def test_tokens_precede_citations_and_exactly_one_terminal_closes_the_stream() -> None:
    model = ScriptedAdapter(
        call("search_catalog", {"query": query_args("agent", domain=FINANCE)}),
        say("A " * 100 + "[cite:r1]"),
    )
    turn = await run_turn(make_engine(model, make_world()), analyst())
    order = {"context": 0, "tool": 1, "token": 2, "citation": 3, "done": 5}
    ranks = [order[n] for n in turn.names]
    assert ranks == sorted(ranks)
    assert turn.names.count("done") == 1 and turn.names[-1] == "done"
    assert len(turn.of("token")) > 1  # long answers are chunked
    assert all(isinstance(e.payload, TokenEvent) for e in turn.of("token"))
