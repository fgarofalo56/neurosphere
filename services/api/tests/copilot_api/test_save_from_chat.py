"""Save-from-chat (PRP-19 round 2 item 10): the ``chart`` event carries ``query_spec`` only when the
server can prove one query tool call supplied the chart's rows, and a saved report accepts it."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from copilot_api_harness import (  # pyright: ignore[reportMissingImports]
    FINANCE,
    OPERATIONS,
    ScriptedAdapter,
    call,
    make_engine,
    make_scope,
    make_world,
    query_args,
    run_turn,
    say,
)
from neurosphere_api.copilot.dependencies import validate_chart_plan_mapping
from neurosphere_api.copilot.models import ChartEvent
from neurosphere_core.errors import ForbiddenError
from neurosphere_core.scope import IdentityScope
from reports_harness import ALICE, BOB, REPORTS_PATH, make_api  # pyright: ignore[reportMissingImports]

FIN_AGENT = "commercial:contoso:foundry:agent:fin-1"
OPS_AGENT = "commercial:contoso:foundry:agent:ops-1"


def analyst(*domains: str) -> IdentityScope:
    return make_scope([("analyst", list(domains))], list(domains))


def plan(*record_ids: str | None) -> dict[str, Any]:
    """A valid plan whose rows carry the record ids they came from (``None`` omits the id)."""
    rows: list[dict[str, Any]] = []
    for n, record_id in enumerate(record_ids, start=1):
        row: dict[str, Any] = {"display_name": f"Agent {n}", "version": float(n)}
        if record_id is not None:
            row["record_id"] = record_id
        rows.append(row)
    return {
        "schema_version": "1.0.0",
        "citations": [{"evidence_id": "ev:agents", "as_of": "2026-10-10T11:58:00Z"}],
        "spec": {
            "title": "Agent versions",
            "data": {"values": rows},
            "mark": "bar",
            "encoding": {
                "x": {"field": "display_name", "type": "nominal"},
                "y": {"field": "version", "type": "quantitative"},
            },
        },
    }


async def chart_events(
    steps: list[Any], scope: IdentityScope, validator: Any = validate_chart_plan_mapping
) -> list[ChartEvent]:
    model = ScriptedAdapter(*steps)
    turn = await run_turn(make_engine(model, make_world(), chart_validator=validator), scope)
    assert turn.terminal.name == "done", turn.terminal.payload
    return [e.payload for e in turn.of("chart") if isinstance(e.payload, ChartEvent)]


def fin_search(call_id: str = "c1", **extra: Any) -> Any:
    return call("search_catalog", {"query": query_args("agent", domain=FINANCE, **extra)}, call_id)


async def test_a_single_call_chart_carries_the_exact_query_and_a_report_accepts_it() -> None:
    charts = await chart_events(
        [
            fin_search(),
            call("render_chart", {"chart_plan": plan(FIN_AGENT)}, "c2"),
            say("Done [cite:r1]."),
        ],
        analyst(FINANCE),
    )
    spec = charts[0].query_spec
    assert spec is not None
    assert spec["entity"] == "agent" and spec["operation"] == "list"
    assert spec["filters"] == [{"field": "domain_id", "op": "eq", "value": FINANCE}]
    assert "query_spec" not in charts[0].chart_plan

    # The reports create path accepts it exactly as emitted; a viewer's run is filtered to them.
    api = make_api()
    body = {"title": "From chat", "chart_plan": charts[0].chart_plan, "query_spec": spec}
    created = api.h.client.post(REPORTS_PATH, headers=api.h.auth(ALICE), json=body)
    assert created.status_code == 201, created.text
    assert created.json()["query_spec"]["entity"] == "agent"
    api.share(ALICE, created.json()["id"], BOB)
    run = api.run(BOB, created.json()["id"])
    assert run.status_code == 200, run.text
    rows = run.json()["chart_plan"]["spec"]["data"]["values"]
    assert {r["record_id"] for r in rows} == {FIN_AGENT, "commercial:contoso:foundry:agent:fin-2"}
    assert all("ops-1" not in r["record_id"] for r in rows)


async def test_a_chart_from_two_tool_calls_has_no_query_spec() -> None:
    charts = await chart_events(
        [
            fin_search("c1"),
            call("search_catalog", {"query": query_args("agent", domain=OPERATIONS)}, "c2"),
            call("render_chart", {"chart_plan": plan(FIN_AGENT, OPS_AGENT)}, "c3"),
            say("Done [cite:r1]."),
        ],
        analyst(FINANCE, OPERATIONS),
    )
    assert charts[0].query_spec is None


async def test_a_chart_whose_rows_no_tool_call_supplied_has_no_query_spec() -> None:
    fabricated = "commercial:contoso:foundry:agent:invented"
    for rows in ((fabricated,), (None,), (FIN_AGENT, fabricated)):
        charts = await chart_events(
            [
                fin_search(),
                call("render_chart", {"chart_plan": plan(*rows)}, "c2"),
                say("Done [cite:r1]."),
            ],
            analyst(FINANCE),
        )
        assert charts[0].query_spec is None


async def test_the_same_result_from_two_calls_is_ambiguous_and_omitted() -> None:
    charts = await chart_events(
        [
            fin_search("c1"),
            fin_search("c2", limit=19),
            call("render_chart", {"chart_plan": plan(FIN_AGENT)}, "c3"),
            say("Done [cite:r1]."),
        ],
        analyst(FINANCE),
    )
    assert charts[0].query_spec is None


async def test_a_model_supplied_query_spec_is_refused_by_the_real_validator() -> None:
    forged = {**plan(FIN_AGENT), "query_spec": query_args("agent", domain=OPERATIONS)}
    model = ScriptedAdapter(
        fin_search(),
        call("render_chart", {"chart_plan": forged}, "c2"),
        say("Done [cite:r1]."),
    )
    engine = make_engine(model, make_world(), chart_validator=validate_chart_plan_mapping)
    turn = await run_turn(engine, analyst(FINANCE))
    assert turn.terminal.name == "denied"
    assert not turn.of("chart")


async def test_a_model_supplied_query_spec_is_never_echoed_by_a_lenient_validator() -> None:
    forged = {**plan(FIN_AGENT), "query_spec": query_args("agent", domain=OPERATIONS)}

    def lenient(raw: Mapping[str, Any]) -> Mapping[str, Any]:
        return dict(raw)  # a validator that lets the extra member through

    charts = await chart_events(
        [
            fin_search(),
            call("render_chart", {"chart_plan": forged}, "c2"),
            say("Done [cite:r1]."),
        ],
        analyst(FINANCE),
        validator=lenient,
    )
    assert "query_spec" not in charts[0].chart_plan
    # The server's own record wins: the emitted query is the finance one that ran.
    spec: Any = charts[0].query_spec
    assert spec is not None
    assert spec["filters"][0]["value"] == FINANCE


async def test_a_denied_validator_still_emits_nothing() -> None:
    def refuse(raw: Mapping[str, Any]) -> Mapping[str, Any]:
        raise ForbiddenError("no", reason="chart_plan_rejected")

    model = ScriptedAdapter(fin_search(), call("render_chart", {"chart_plan": plan(FIN_AGENT)}))
    turn = await run_turn(
        make_engine(model, make_world(), chart_validator=refuse), analyst(FINANCE)
    )
    assert not turn.of("chart")
