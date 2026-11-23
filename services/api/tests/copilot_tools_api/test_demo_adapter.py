"""The recorded demo adapter (PRP-78 item 6) through the REAL engine and tool registry.

The ports are real in-memory classes seeded so every tool returns rows; the adapter only ever
sees ``cite_as`` handles, so an answer that resolves proves handles are read from the tool turns.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast

import pytest
from action_plane_harness import ALICE  # pyright: ignore[reportMissingImports]
from copilot_api_harness import (  # pyright: ignore[reportMissingImports]
    FINANCE,
    NOW,
    OPERATIONS,
    SCHEMAS,
    World,
    agent,
    make_scope,
    make_world,
    run_turn,
)
from copilot_http_harness import COPILOT_PREFIX, make_http  # pyright: ignore[reportMissingImports]
from neurosphere_api.copilot import CopilotExtraPorts
from neurosphere_api.copilot.models import MessageContext
from neurosphere_contracts.catalog.v1.grounding_source import GroundingSource
from neurosphere_contracts.recommendations.v1.agent_match_request import AgentMatchRequest
from neurosphere_contracts.recommendations.v1.agent_match_response import AgentMatchResponse
from neurosphere_core.catalog.graph import RepositoryGraphQuery
from neurosphere_core.catalog.graph.access import AccessEngine
from neurosphere_core.catalog.protocol import CatalogEdge
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.copilot.models import (
    AdapterDescriptor,
    ModelEvent,
    ModelRequest,
    RecordedDemoAdapter,
    ToolCallRequested,
)
from neurosphere_core.copilot.models.demo import (
    DEMO_DIR,
    compose_answer,
    load_demo_scripts,
    match_script,
)
from neurosphere_core.copilot.tools.args import CostSummaryArgs, SearchCatalogArgs
from neurosphere_core.copilot.tools.graph import GraphQueryArgs
from neurosphere_core.copilot.tools.matching import RecommendAgentArgs
from neurosphere_core.copilot.tools.ports import ChangeRecord
from neurosphere_core.copilot.tools.timeline import META_RECORD_ID, TimelineArgs
from neurosphere_core.scope import IdentityScope
from pydantic import TypeAdapter
from tools_harness import make_tools_engine  # pyright: ignore[reportMissingImports]

CUSTOMER = "contoso"
WRITER = f"commercial:{CUSTOMER}:foundry:agent:invoice-intake"
READER = f"commercial:{CUSTOMER}:foundry:agent:ticket-reader"
# The source the "who writes" question names: the demo world's "Accounts Payable Invoices"
# (sandbox/demo/data/data_assets.json, slug ap-invoices, residency eu_eea, domain finance).
AP_SOURCE = f"commercial:{CUSTOMER}:foundry:grounding_source:ap-invoices"
US_SOURCE = f"commercial:{CUSTOMER}:foundry:grounding_source:us-logs"
EDGES = TypeAdapter(CatalogEdge)

ARG_MODELS: dict[str, Any] = {
    "search_catalog": SearchCatalogArgs,
    "graph_query": GraphQueryArgs,
    "get_timeline": TimelineArgs,
    "recommend_agent": RecommendAgentArgs,
    "get_cost_summary": CostSummaryArgs,
}

QUESTIONS: dict[str, str] = {
    "eu_customer_data_agents": "Which agents touch EU customer data?",
    "who_writes_to_source": "Which agents write to the Accounts Payable Invoices source?",
    "what_changed_last_hour": "What changed in the last hour?",
    "agent_for_ticket_summary": "Which agent should summarize a support ticket?",
    "spend_this_week": "What did we spend this week?",
}


def _example(rel: str) -> dict[str, Any]:
    return json.loads((SCHEMAS / rel).read_text(encoding="utf-8"))


def _source(name: str, **patch: Any) -> GroundingSource:
    raw = _example("catalog/v1/examples/valid/grounding_source.sensitivity-residency.json")
    raw.update(
        id=f"commercial:{CUSTOMER}:foundry:grounding_source:{name}",
        customer_id=CUSTOMER,
        domain_id=FINANCE,
        version=1,
        etag="caller-etag",
        display_name=f"Source {name}",
        tags=[],
        environment="unknown",
    )
    raw.update(patch)
    return GroundingSource.model_validate(raw)


def _edge(relation: str, name: str, who: str, what: str) -> CatalogEdge:
    raw = _example(f"catalog/v1/examples/valid/{relation}.inferred.json")
    raw.update(
        id=f"commercial:{CUSTOMER}:neurosphere:{relation}:{name}",
        source_id=who,
        target_id=what,
        customer_id=CUSTOMER,
        domain_id=FINANCE,
        version=1,
        etag="caller-etag",
    )
    return EDGES.validate_python(raw)


class _NoSearch:
    async def search(self, scope: object, request: object) -> Any:
        raise AssertionError("the demo scripts never run a text search")


@dataclass
class FakeChanges:
    async def changes(
        self, scope: IdentityScope, domain_ids: Any, since: Any, until: Any, *, limit: int
    ) -> list[ChangeRecord]:
        return [
            ChangeRecord(
                record_id="audit-1",
                operation="catalog.update",
                subject_id=WRITER,
                outcome="success",
                occurred_at=NOW - timedelta(minutes=10),
                domain_id=FINANCE,
            )
        ]


class FakeMatcher:
    def __init__(self, *, empty: bool = False) -> None:
        self.empty = empty

    async def match(
        self, scope: IdentityScope, domain: str, request: AgentMatchRequest
    ) -> AgentMatchResponse:
        assert "summarize" in request.task_text
        return AgentMatchResponse.model_validate(
            {
                "schema_version": "1.0.0",
                "match_id": "match-0001",
                "domain_id": domain,
                "generated_at": "2026-10-21T11:00:00Z",
                "ranker": {"ranker_id": "weighted-signals", "ranker_version": "1.0.0"},
                "cold_start": False,
                "signals_unavailable": [],
                "candidates": []
                if self.empty
                else [
                    {
                        "rank": 1,
                        "entity_id": READER,
                        "entity_type": "agent",
                        "display_name": "Ticket Reader",
                        "lifecycle_status": "active",
                        "score": 0.9,
                        "signals": [],
                        "matched_capabilities": [],
                        "matched_tags": [],
                        "relations": [],
                        "evidence_ids": [],
                    }
                ],
                "truncated": False,
                "partial_reason": None,
            }
        )


def _auditor_scope() -> IdentityScope:
    return make_scope([("domain_steward", [FINANCE]), ("security_auditor", [FINANCE])], [FINANCE])


async def _seeded() -> tuple[World, CopilotExtraPorts]:
    seed = make_scope([("viewer", [FINANCE])], [FINANCE])
    repo = InMemoryCatalogRepository()
    graph = RepositoryGraphQuery(repo, cast(Any, _NoSearch()), now=lambda: NOW)
    for entity in (agent(WRITER, FINANCE), agent(READER, FINANCE)):
        await repo.create_entity(seed, entity)
    await repo.create_entity(
        seed,
        _source(
            "ap-invoices",
            sensitivity_categories=["pii"],
            contains_personal_data=True,
            residency_region="westeurope",
            residency_geography="eu_eea",
        ),
    )
    await repo.create_entity(
        seed,
        _source(
            "us-logs",
            sensitivity_categories=["pii"],
            contains_personal_data=True,
            residency_region="eastus",
            residency_geography="united_states",
        ),
    )
    await repo.put_edge(seed, _edge("writes", "w-ap", WRITER, AP_SOURCE), None)
    await repo.put_edge(seed, _edge("reads", "r-ap", READER, AP_SOURCE), None)
    world = make_world()
    world.catalog = cast(Any, repo)
    ports = CopilotExtraPorts(
        graph=graph,
        access=AccessEngine(repo, graph, now=lambda: NOW),
        changes=FakeChanges(),
        matcher=FakeMatcher(),
    )
    return world, ports


class Recording:
    """Wraps the demo adapter and keeps every tool call it emitted."""

    def __init__(self) -> None:
        self.inner = RecordedDemoAdapter(clock=lambda: NOW)
        self.calls: list[ToolCallRequested] = []
        self.requests: list[ModelRequest] = []

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self.inner.descriptor

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        self.requests.append(request)
        async for event in self.inner.stream(request):
            if isinstance(event, ToolCallRequested):
                self.calls.append(event)
            yield event


async def _ask(question: str) -> tuple[Any, Recording]:
    world, ports = await _seeded()
    adapter = Recording()
    engine = make_tools_engine(cast(Any, adapter), world, extra_ports=ports)
    turn = await run_turn(engine, _auditor_scope(), question)
    return turn, adapter


def test_the_five_demo_questions_are_all_scripted_and_match_their_own_question() -> None:
    scripts = {s.id: s for s in load_demo_scripts()}
    assert set(scripts) == set(QUESTIONS)
    assert len(list(DEMO_DIR.glob("*.json"))) == 5
    for script_id, question in QUESTIONS.items():
        matched = match_script(question)
        assert matched is not None and matched.id == script_id
        assert scripts[script_id].question == question


@pytest.mark.parametrize(
    ("script_id", "expect_text", "expect_ids"),
    [
        ("eu_customer_data_agents", "invoice-intake", {WRITER, READER}),
        ("who_writes_to_source", "invoice-intake", {WRITER}),
        ("what_changed_last_hour", "catalog.update", {"audit-1"}),
        ("agent_for_ticket_summary", "Ticket Reader", {READER}),
        ("spend_this_week", "12.50", None),
    ],
)
async def test_each_demo_question_answers_with_citations_that_resolve(
    script_id: str, expect_text: str, expect_ids: set[str] | None
) -> None:
    turn, adapter = await _ask(QUESTIONS[script_id])
    assert turn.terminal.name == "done", [e.name for e in turn.events]
    assert expect_text in turn.text
    citations = [e.payload for e in turn.of("citation")]
    assert citations
    cited = {c.record_id for c in citations}
    if expect_ids is not None:
        assert expect_ids <= cited
        assert not cited - expect_ids - {AP_SOURCE, US_SOURCE}
    assert META_RECORD_ID not in cited and META_RECORD_ID not in turn.text
    # Every emitted call validates against the real argument model of its tool.
    assert adapter.calls
    for call in adapter.calls:
        ARG_MODELS[call.tool_name].model_validate(call.arguments)
    # The model is only ever shown handles, and the answer cites those handles.
    assert "[cite:" not in turn.text


async def test_who_writes_resolves_the_source_id_from_the_first_step_result() -> None:
    turn, adapter = await _ask(QUESTIONS["who_writes_to_source"])
    assert turn.terminal.name == "done"
    first, second = adapter.calls
    assert first.tool_name == "search_catalog"
    assert second.tool_name == "graph_query"
    assert second.arguments["query"]["traversal"]["start_ids"] == [AP_SOURCE]
    # The writer is cited, the reader of the same source is not.
    assert READER not in {e.payload.record_id for e in turn.of("citation")}


@pytest.mark.parametrize("script_id", sorted(QUESTIONS))
async def test_each_demo_question_still_answers_when_the_dock_is_narrowed(script_id: str) -> None:
    """A domain selected in the dock narrows every tool call; no demo question may be refused."""
    world, ports = await _seeded()
    adapter = Recording()
    engine = make_tools_engine(cast(Any, adapter), world, extra_ports=ports)
    scope = make_scope(
        [("domain_steward", [FINANCE, OPERATIONS]), ("security_auditor", [FINANCE, OPERATIONS])],
        [FINANCE, OPERATIONS],
    )
    turn = await run_turn(
        engine, scope, QUESTIONS[script_id], hint=MessageContext(domain_id=FINANCE)
    )
    assert turn.events[0].payload.applied_domains == [FINANCE]
    assert turn.terminal.name == "done", [e.name for e in turn.events]
    assert [e.payload for e in turn.of("citation")]


async def test_the_cost_window_is_seven_days_ending_at_the_adapter_clock() -> None:
    _, adapter = await _ask(QUESTIONS["spend_this_week"])
    (call,) = adapter.calls
    window = call.arguments["query"]["time_range"]
    assert window == {"start": "2026-10-14T12:00:00Z", "end": "2026-10-21T12:00:00Z"}


async def test_an_unmatched_question_abstains_without_a_tool_call() -> None:
    turn, adapter = await _ask("What is the airspeed velocity of an unladen swallow?")
    assert turn.terminal.name == "abstain"
    assert adapter.calls == []
    assert not turn.of("citation")


async def test_an_empty_tool_result_is_never_filled_with_an_invented_answer() -> None:
    world, ports = await _seeded()
    empty = CopilotExtraPorts(
        graph=ports.graph, access=ports.access, changes=None, matcher=FakeMatcher(empty=True)
    )
    engine = make_tools_engine(cast(Any, Recording()), world, extra_ports=empty)
    turn = await run_turn(engine, _auditor_scope(), QUESTIONS["agent_for_ticket_summary"])
    assert turn.terminal.name == "abstain"
    assert not turn.of("citation")


def test_timeline_meta_is_never_quoted_or_cited() -> None:
    script = match_script(QUESTIONS["what_changed_last_hour"])
    assert script is not None
    payload = {
        "records": [
            {
                "record_id": META_RECORD_ID,
                "kind": "timeline_meta",
                "data": {"sections_included": ["changes"]},
                "cite_as": "r1",
            },
            {
                "record_id": "audit-1",
                "kind": "change",
                "data": {"operation": "catalog.update", "outcome": "success"},
                "cite_as": "r2",
            },
        ]
    }
    text = compose_answer(script, payload)
    assert "[cite:r2]" in text and "[cite:r1]" not in text and "sections_included" not in text
    only_meta = compose_answer(script, {"records": [payload["records"][0]]})
    assert "[cite:" not in only_meta


def test_handles_come_from_the_tool_turns_and_are_never_invented() -> None:
    script = match_script(QUESTIONS["agent_for_ticket_summary"])
    assert script is not None
    payload = {
        "records": [
            {"record_id": "a", "kind": "agent", "data": {"display_name": "Alpha"}, "cite_as": "r7"},
            {"record_id": "b", "kind": "agent", "data": {"display_name": "Beta"}},  # no handle
        ]
    }
    text = compose_answer(script, payload)
    assert "Alpha" in text and "[cite:r7]" in text
    assert "Beta" not in text and "[cite:r1]" not in text


def test_the_status_route_reports_the_demo_adapter_as_synthetic() -> None:
    http = make_http(cast(Any, RecordedDemoAdapter()))
    response = http.client.get(f"{COPILOT_PREFIX}/status", headers=http.headers(ALICE))
    assert response.status_code == 200
    assert response.json() == {"state": "ready", "reason_code": None, "synthetic": True}
