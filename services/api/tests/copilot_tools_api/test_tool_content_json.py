"""Guard: tool content the model receives stays valid JSON after prompt redaction.

The card-number redaction pattern matches long float fractions, which used to turn
``{"score": 0.8589208973118884}`` into ``{"score": 0.[card]}`` (invalid JSON). Floats are now
bounded before serialization; these tests pin that for realistic payloads and for the demo turn.
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from copilot_api_harness import run_turn  # pyright: ignore[reportMissingImports]
from neurosphere_api.copilot import CopilotExtraPorts
from neurosphere_api.copilot.engine import _Run, _tool_content  # pyright: ignore[reportPrivateUsage]
from neurosphere_contracts.recommendations.v1.agent_match_request import AgentMatchRequest
from neurosphere_contracts.recommendations.v1.agent_match_response import AgentMatchResponse
from neurosphere_core.copilot.tools.models import ToolRecord, ToolResult
from neurosphere_core.scope import IdentityScope
from test_demo_adapter import (  # pyright: ignore[reportMissingImports]
    QUESTIONS,
    READER,
    Recording,
    _auditor_scope,  # pyright: ignore[reportPrivateUsage]
    _seeded,  # pyright: ignore[reportPrivateUsage]
)
from tools_harness import make_tools_engine  # pyright: ignore[reportMissingImports]

LONG = 0.8589208973118884


def _content(tool: str, records: list[tuple[str, str, dict[str, Any]]]) -> tuple[Any, _Run]:
    result = ToolResult(
        tool=tool,
        records=tuple(ToolRecord(record_id=i, kind=k, data=d) for i, k, d in records),
        citations=(),
    )
    state = _Run()
    return json.loads(_tool_content(result, state)), state


def test_recommend_agent_long_float_scores_and_signals_stay_valid_json() -> None:
    payload, state = _content(
        "recommend_agent",
        [
            (
                "agent-1",
                "agent",
                {
                    "rank": 1,
                    "score": LONG,
                    "signals": [
                        {"name": "capability", "weight": 0.1234567890123456, "value": LONG}
                    ],
                    "nested": {"deep": [0.3333333333333333]},
                },
            )
        ],
    )
    data = payload["records"][0]["data"]
    assert data["score"] == pytest.approx(0.858921)
    assert data["signals"][0]["weight"] == pytest.approx(0.123457)
    assert data["nested"]["deep"] == [0.333333]
    assert data["rank"] == 1 and isinstance(data["rank"], int)
    assert payload["records"][0]["cite_as"] == "r1"
    assert state.aliases == {"r1": "agent-1"}


def test_cost_aggregate_payload_stays_valid_json() -> None:
    payload, _ = _content(
        "get_cost_summary",
        [
            (
                "cost-1",
                "cost_aggregate",
                {
                    "total_cost": 12.500000000000002,
                    "avg_latency_ms": 183.33333333333334,
                    "input_tokens": 123456,
                    "currency": "USD",
                    "share": 0.6666666666666666,
                },
            )
        ],
    )
    data = payload["records"][0]["data"]
    assert data["total_cost"] == 12.5
    assert data["input_tokens"] == 123456
    assert data["currency"] == "USD"


def test_graph_query_payload_stays_valid_json() -> None:
    payload, _ = _content(
        "graph_query",
        [
            ("n1", "node", {"id": "n1", "confidence": 0.9876543210987654, "hops": 2}),
            ("e1", "edge", {"source": "n1", "target": "n2", "weight": 0.1111111111111111}),
        ],
    )
    assert [r["cite_as"] for r in payload["records"]] == ["r1", "r2"]
    assert payload["records"][0]["data"]["confidence"] == pytest.approx(0.987654)
    assert payload["records"][0]["data"]["hops"] == 2


class _LongFloatMatcher:
    async def match(
        self, scope: IdentityScope, domain: str, request: AgentMatchRequest
    ) -> AgentMatchResponse:
        return AgentMatchResponse.model_validate(
            {
                "schema_version": "1.0.0",
                "match_id": "match-0001",
                "domain_id": domain,
                "generated_at": "2026-10-21T11:00:00Z",
                "ranker": {"ranker_id": "weighted-signals", "ranker_version": "1.0.0"},
                "cold_start": False,
                "signals_unavailable": [],
                "candidates": [
                    {
                        "rank": 1,
                        "entity_id": READER,
                        "entity_type": "agent",
                        "display_name": "Ticket Reader",
                        "lifecycle_status": "active",
                        "score": LONG,
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


async def test_demo_recommend_question_with_long_float_scores_ends_done_with_citations() -> None:
    world, ports = await _seeded()
    long_ports = CopilotExtraPorts(
        graph=ports.graph,
        access=ports.access,
        changes=ports.changes,
        matcher=cast(Any, _LongFloatMatcher()),
    )
    engine = make_tools_engine(cast(Any, Recording()), world, extra_ports=long_ports)
    turn = await run_turn(engine, _auditor_scope(), QUESTIONS["agent_for_ticket_summary"])
    assert turn.terminal.name == "done", [e.name for e in turn.events]
    assert "Ticket Reader" in turn.text
    assert {e.payload.record_id for e in turn.of("citation")} >= {READER}
