"""Injection cases for the PRP-78 tools through the real engine (PRP-78 item 5, criterion 7).

A compromised model smuggles traversal keys, inflated budgets, scope-shaped keys and oversize
timeline windows. Each call must be refused before any port is read: the recording ports below
stay empty ("zero overscoped rows") and no ``ok`` tool event exists for the offending call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

import pytest
from copilot_api_harness import (  # pyright: ignore[reportMissingImports]
    FINANCE,
    OPERATIONS,
    ScriptedAdapter,
    World,
    call,
    make_scope,
    make_world,
    run_turn,
)
from neurosphere_api.copilot.models import ToolEvent
from neurosphere_api.copilot.tooling import CopilotExtraPorts
from tools_harness import make_tools_engine  # pyright: ignore[reportMissingImports]

FIN_AGENT = "commercial:contoso:foundry:agent:fin-1"
OPS_AGENT = "commercial:contoso:foundry:agent:ops-1"


@dataclass
class RecordingGraph:
    calls: list[str] = field(default_factory=list[str])

    async def neighbors(self, scope: Any, request: Any) -> Any:
        self.calls.append("neighbors")
        raise AssertionError("a refused call reached the graph port")

    async def impact_paths(self, scope: Any, request: Any) -> Any:
        self.calls.append("impact_paths")
        raise AssertionError("a refused call reached the graph port")


@dataclass
class RecordingMatcher:
    calls: list[str] = field(default_factory=list[str])

    async def match(self, scope: Any, domain: str, request: Any) -> Any:
        self.calls.append(domain)
        raise AssertionError("a refused call reached the matcher port")


def graph_query(
    *,
    relations: list[str] | None = None,
    depth: int = 2,
    budget: dict[str, Any] | None = None,
    traversal: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "query": {
            "schema_version": "1.0.0",
            "operation": "neighbors",
            "entity": "agent",
            "traversal": traversal
            or {
                "start_ids": [FIN_AGENT],
                "relations": relations or ["invokes"],
                "direction": "outgoing",
            },
            "budget": budget or {"timeout_ms": 2000, "limit": 20, "max_depth": depth},
            **extra,
        }
    }


async def refused_turn(
    tool: str, args: dict[str, Any]
) -> tuple[RecordingGraph, RecordingMatcher, World, list[ToolEvent], str]:
    graph, matcher, world = RecordingGraph(), RecordingMatcher(), make_world()
    ports = CopilotExtraPorts(graph=cast(Any, graph), matcher=cast(Any, matcher))
    scope = make_scope([("analyst", [FINANCE])], [FINANCE])
    turn = await run_turn(
        make_tools_engine(ScriptedAdapter(call(tool, args)), world, extra_ports=ports), scope
    )
    events = [e.payload for e in turn.of("tool") if isinstance(e.payload, ToolEvent)]
    return graph, matcher, world, events, turn.terminal.name


def assert_refused(
    graph: RecordingGraph,
    matcher: RecordingMatcher,
    world: World,
    events: list[ToolEvent],
    terminal: str,
) -> None:
    assert not graph.calls and not matcher.calls
    assert not world.domains_asked()  # zero overscoped (indeed zero) rows read
    assert all(e.status != "ok" for e in events)
    assert events and events[-1].status == "refused"
    assert terminal != "done"


# -- traversal smuggling --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        graph_query(relations=["grants_access_to"]),
        graph_query(relations=["invokes", "grants_access_to"]),
        graph_query(relations=["not_a_relation"]),
        graph_query(
            traversal={"start_ids": [FIN_AGENT], "relations": ["invokes"], "direction": "up"}
        ),
        graph_query(
            traversal={
                "start_ids": [FIN_AGENT],
                "relations": ["invokes"],
                "direction": "outgoing",
                "follow_all": True,
            }
        ),
        graph_query(traversal={"start_ids": [FIN_AGENT], "relations": [], "direction": "both"}),
        graph_query(start_cypher="MATCH (n) RETURN n"),
    ],
    ids=[
        "grants_access_to",
        "grants_access_to_mixed",
        "unknown_relation",
        "bad_direction",
        "extra_traversal_key",
        "empty_relations",
        "extra_query_key",
    ],
)
async def test_traversal_smuggling_is_refused(args: dict[str, Any]) -> None:
    assert_refused(*await refused_turn("graph_query", args))


# -- depth and budget inflation -------------------------------------------------------------------


@pytest.mark.parametrize(
    "budget",
    [
        {"timeout_ms": 2000, "limit": 20, "max_depth": 4},
        {"timeout_ms": 2000, "limit": 20, "max_depth": 5},
        {"timeout_ms": 2000, "limit": 20, "max_depth": 6},
        {"timeout_ms": 2000, "limit": 20, "max_depth": -1},
        {"timeout_ms": 2000, "limit": 20, "max_depth": 2, "max_nodes": 5001},
        {"timeout_ms": 2000, "limit": 1001, "max_depth": 2},
        {"timeout_ms": 30001, "limit": 20, "max_depth": 2},
        {"timeout_ms": 2000, "limit": 20, "max_depth": "3"},
    ],
    ids=[
        "depth_4",
        "depth_5",
        "depth_6",
        "depth_negative",
        "nodes_5001",
        "limit_1001",
        "timeout_30001",
        "depth_string",
    ],
)
async def test_depth_and_budget_inflation_is_refused(budget: dict[str, Any]) -> None:
    assert_refused(*await refused_turn("graph_query", graph_query(budget=budget)))


# -- timeline window inflation --------------------------------------------------------------------


@pytest.mark.parametrize("window", [1441, 100000, 0, -60, 4, "60", 60.5, None, True])
async def test_timeline_window_inflation_is_refused(window: object) -> None:
    assert_refused(*await refused_turn("get_timeline", {"window_minutes": window}))


async def test_timeline_unknown_section_and_budget_inflation_are_refused() -> None:
    assert_refused(
        *await refused_turn("get_timeline", {"window_minutes": 60, "sections": ["secrets"]})
    )
    assert_refused(
        *await refused_turn(
            "get_timeline",
            {"window_minutes": 60, "budget": {"timeout_ms": 2000, "limit": 5000, "max_depth": 0}},
        )
    )


# -- scope-shaped keys ----------------------------------------------------------------------------

SCOPE_KEYS = ["domain_id", "domainIds", "customer_id", "tenant", "scope", "roles", "principal"]


@pytest.mark.parametrize("key", SCOPE_KEYS)
@pytest.mark.parametrize("tool", ["graph_query", "get_timeline", "recommend_agent"])
async def test_scope_shaped_top_level_keys_are_refused(tool: str, key: str) -> None:
    base: dict[str, Any] = {
        "graph_query": graph_query(),
        "get_timeline": {"window_minutes": 60},
        "recommend_agent": {"request": {"task": "summarize a ticket"}},
    }[tool]
    assert_refused(*await refused_turn(tool, {**base, key: OPERATIONS}))


@pytest.mark.parametrize("key", ["domain_id", "customer_id", "domain_ids"])
async def test_scope_shaped_keys_nested_in_request_are_refused(key: str) -> None:
    args: dict[str, Any] = {"request": {"task": "summarize a ticket", key: OPERATIONS}}
    assert_refused(*await refused_turn("recommend_agent", args))


async def test_a_domain_outside_the_scope_in_a_graph_start_id_reads_nothing() -> None:
    graph = RecordingGraph()
    world = make_world()
    scope = make_scope([("analyst", [FINANCE])], [FINANCE])
    ports = CopilotExtraPorts(graph=cast(Any, graph))
    args = graph_query(
        traversal={"start_ids": [OPS_AGENT], "relations": ["invokes"], "direction": "outgoing"}
    )
    turn = await run_turn(
        make_tools_engine(ScriptedAdapter(call("graph_query", args)), world, extra_ports=ports),
        scope,
    )
    assert not world.domains_asked() - {FINANCE}
    assert not any(d == OPERATIONS for d in world.domains_asked())
    assert turn.terminal.name != "done"
