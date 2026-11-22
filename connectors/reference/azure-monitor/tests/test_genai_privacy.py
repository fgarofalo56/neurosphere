"""Privacy proofs for the GenAI mapper (PRP-141 item 1): no content value reaches an event."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from neurosphere_connector_azure_monitor import map_genai_row

FIXTURES = Path(__file__).parent / "fixtures"
ARGS: dict[str, Any] = {
    "cloud": "commercial",
    "customer_id": "cust-1",
    "source_id": "azure-monitor-ai",
    "domain_id": "dom-1",
}


def _rows(name: str) -> list[dict[str, Any]]:
    table = json.loads((FIXTURES / name).read_text(encoding="utf-8"))["tables"][0]
    names = [c["name"] for c in table["columns"]]
    return [dict(zip(names, row, strict=True)) for row in table["rows"]]


def test_fixture_content_row_really_carries_markers() -> None:
    row = _rows("genai_dependencies_response.json")[5]
    assert row["gen_ai.input.messages"] == "CONTENT-MARKER-1"
    assert row["gen_ai.output.messages"] == "CONTENT-MARKER-2"
    assert row["gen_ai.tool.call.arguments"] == "CONTENT-MARKER-3"


def test_serialized_event_never_contains_content_markers() -> None:
    row = _rows("genai_dependencies_response.json")[5]
    event = map_genai_row(row, **ARGS)
    assert event.span_kind == "model_call"
    assert "CONTENT-MARKER" not in event.model_dump_json()


def test_unknown_columns_are_ignored_for_every_fixture_row() -> None:
    rows = _rows("genai_dependencies_response.json") + _rows("genai_requests_response.json")
    mapped = 0
    for row in rows:
        row = {**row, "Properties": "CONTENT-MARKER-9", "Name": "CONTENT-MARKER-8"}
        try:
            event = map_genai_row(row, **ARGS)
        except ValueError:
            continue
        mapped += 1
        assert "CONTENT-MARKER" not in event.model_dump_json()
    assert mapped >= 5


def test_event_has_no_payload_reference_and_no_canonical_agent() -> None:
    for row in _rows("genai_dependencies_response.json"):
        try:
            event = map_genai_row(row, **ARGS)
        except ValueError:
            continue
        assert event.payload_ref is None
        assert event.canonical_agent_id is None
