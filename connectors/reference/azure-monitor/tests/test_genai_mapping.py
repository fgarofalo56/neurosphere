"""GenAI row mapping (PRP-141 item 1) on HAND-BUILT fixtures (see the fixture _comment)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from neurosphere_connector_azure_monitor import GenAiRowSkipped, map_genai_row

FIXTURES = Path(__file__).parent / "fixtures"
TRACE = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
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


DEPS = _rows("genai_dependencies_response.json")
REQS = _rows("genai_requests_response.json")


def test_model_call() -> None:
    event = map_genai_row(DEPS[0], **ARGS)
    assert event.event_id.root == f"{TRACE}:1111111111111111"
    assert event.trace_id is not None and event.trace_id.root == TRACE
    assert event.span_id is not None and event.span_id.root == "1111111111111111"
    assert event.parent_span_id is not None and event.parent_span_id.root == "aaaaaaaaaaaaaaaa"
    assert event.span_kind == "model_call"
    assert event.provider is not None and event.provider.root == "azure.ai.openai"
    # response model comes first in the edge's MODEL_ATTRS order
    assert event.model is not None and event.model.root == "gpt-4o-2024-08-06"
    assert event.outcome == "success"
    assert event.duration_ms == 812
    assert event.token_breakdown is not None
    assert event.token_breakdown.input == 120
    assert event.token_breakdown.output == 45
    assert event.token_breakdown.cached is None
    assert event.token_breakdown.reasoning is None
    assert event.event_time.root == "2026-11-22T10:00:00.123456Z"
    assert event.sampling is None
    assert event.domain_id is not None and event.domain_id.root == "dom-1"


def test_tool_call_has_no_model_or_tokens() -> None:
    event = map_genai_row(DEPS[1], **ARGS)
    assert event.span_kind == "tool_call"
    assert event.model is None
    assert event.token_breakdown is None
    assert event.duration_ms == 35


def test_agent_run_from_requests() -> None:
    event = map_genai_row(REQS[0], **ARGS)
    assert event.span_kind == "agent_run"
    assert event.duration_ms == 2500
    assert event.parent_span_id is None


def test_failed_call() -> None:
    event = map_genai_row(DEPS[2], **ARGS)
    assert event.outcome == "error"
    assert event.provider is not None and event.provider.root == "openai"
    assert event.token_breakdown is None


def test_sampled_row_records_rate_and_never_scales() -> None:
    event = map_genai_row(DEPS[3], **ARGS)
    assert event.sampling is not None
    assert event.sampling.rate == pytest.approx(0.25)
    assert event.sampling.method == "unknown"
    unsampled = map_genai_row(DEPS[0], **ARGS)
    assert unsampled.sampling is None


def test_string_tokens_parse_and_non_numeric_is_none_not_zero() -> None:
    event = map_genai_row(DEPS[3], **ARGS)
    assert event.token_breakdown is not None
    assert event.token_breakdown.input == 10
    assert event.token_breakdown.output is None


def test_missing_tokens_are_none() -> None:
    row = {**DEPS[0]}
    for key in list(row):
        if "usage" in key:
            row[key] = None
    assert map_genai_row(row, **ARGS).token_breakdown is None


def test_edge_fallback_order_for_tokens_and_provider() -> None:
    row = {
        **DEPS[0],
        "gen_ai.usage.input_tokens": "",
        "gen_ai.usage.prompt_tokens": "7",
        "gen_ai.provider.name": None,
        "gen_ai.system": "sys",
        "gen_ai.usage.reasoning_tokens": "0",
    }
    event = map_genai_row(row, **ARGS)
    assert event.token_breakdown is not None
    assert event.token_breakdown.input == 7
    assert event.token_breakdown.reasoning == 0  # a measured zero stays 0
    assert event.provider is not None and event.provider.root == "sys"


@pytest.mark.parametrize(
    ("value", "outcome"),
    [
        (True, "success"),
        ("True", "success"),
        (False, "error"),
        ("False", "error"),
        (None, "unknown"),
    ],
)
def test_outcome(value: Any, outcome: str) -> None:
    assert map_genai_row({**DEPS[0], "Success": value}, **ARGS).outcome == outcome


def test_unknown_operation_maps_to_unknown_kind() -> None:
    row = {**DEPS[0], "gen_ai.operation.name": "brand_new_op"}
    assert map_genai_row(row, **ARGS).span_kind == "unknown"


def test_ids_are_normalized_to_lowercase() -> None:
    row = {**DEPS[0], "OperationId": TRACE.upper(), "Id": "ABCDEF0123456789"}
    event = map_genai_row(row, **ARGS)
    assert event.event_id.root == f"{TRACE}:abcdef0123456789"


def test_agent_id_goes_to_external_only() -> None:
    event = map_genai_row(DEPS[0], **ARGS)
    assert event.external_agent_id is not None
    assert event.external_agent_id.root == "support-bot"
    assert event.canonical_agent_id is None
    assert map_genai_row(DEPS[2], **ARGS).external_agent_id is None


def _reason(row: dict[str, Any], **kw: Any) -> str:
    with pytest.raises(GenAiRowSkipped) as info:
        map_genai_row(row, **{**ARGS, **kw})
    return info.value.reason


def test_guid_ids_are_skipped_as_bad_ids() -> None:
    assert _reason(DEPS[4]) == "bad_ids"


@pytest.mark.parametrize("field", ["OperationId", "Id"])
def test_bad_ids_skip(field: str) -> None:
    assert _reason({**DEPS[0], field: "xyz"}) == "bad_ids"
    assert _reason({**DEPS[0], field: None}) == "bad_ids"
    assert _reason({**DEPS[0], field: "abc"}) == "bad_ids"


def test_no_operation_and_bad_time_skip() -> None:
    assert _reason({**DEPS[0], "gen_ai.operation.name": None}) == "no_operation"
    assert _reason({**DEPS[0], "TimeGenerated": None}) == "bad_time"
    assert _reason({**DEPS[0], "TimeGenerated": "not a time"}) == "bad_time"


def test_role_filter() -> None:
    assert _reason(DEPS[0], app_role_names=["other"]) == "role_filtered"
    assert map_genai_row(DEPS[0], **ARGS, app_role_names=["support-api"]).span_kind == "model_call"
    assert map_genai_row(DEPS[0], **ARGS, app_role_names=None).span_kind == "model_call"


def test_skip_is_a_value_error() -> None:
    assert issubclass(GenAiRowSkipped, ValueError)
