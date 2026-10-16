"""Null stays null: missing optional fields are never defaulted to 0 by normalization."""

from __future__ import annotations

import asyncio
import copy
from typing import Any

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st
from neurosphere_contracts.cost.v1.cost_record import CostRecord
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_workers.ingestion.models import NormalizedEvent
from neurosphere_workers.ingestion.pipeline import process_batch

from .support import Doc, Harness, raw_event, settings

TELEMETRY_OPTIONAL = (
    "model",
    "model_version",
    "provider",
    "duration_ms",
    "token_breakdown",
    "data_source_refs",
    "sampling",
    "request_id",
    "external_agent_id",
    "retry_attempt",
    "domain_id",
)
COST_OPTIONAL = (
    "token_breakdown",
    "retry_count",
    "retry_amount",
    "allocation",
    "event_ids",
    "domain_id",
    "model",
    "model_version",
    "provider",
    "usage_start",
)


def _numbers(node: Any, path: str = "") -> dict[str, float]:
    found: dict[str, float] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            found.update(_numbers(value, f"{path}/{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.update(_numbers(value, f"{path}/{index}"))
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        found[path] = node
    return found


def _normalize(harness: Harness, doc: Doc, kind: str) -> NormalizedEvent:
    result = asyncio.run(process_batch([raw_event(doc, 0, kind=kind)], harness.deps(), settings()))
    assert result.accepted == 1, result
    return next(iter(harness.ledger.effects.values()))


def _assert_no_invented_numbers(event: NormalizedEvent, source: Doc) -> None:
    produced = _numbers(event.contract.model_dump(mode="json", exclude_none=True))
    original = _numbers(source)
    invented = {path: value for path, value in produced.items() if path not in original}
    assert not invented, f"normalization invented numeric fields: {invented}"


async def test_missing_optional_telemetry_fields_stay_null(harness: Harness, template: Doc) -> None:
    doc = copy.deepcopy(template)
    for name in ("duration_ms", "token_breakdown", "retry_attempt", "sampling"):
        doc.pop(name, None)

    await process_batch([raw_event(doc, 0)], harness.deps(), settings())

    event = next(iter(harness.archive.effects.values()))
    contract = event.contract
    assert isinstance(contract, TelemetryEvent)
    assert contract.duration_ms is None
    assert contract.token_breakdown is None
    assert contract.retry_attempt is None
    assert contract.sampling is None


async def test_partial_token_breakdown_keeps_unreported_counts_null(
    harness: Harness, template: Doc
) -> None:
    doc = {**copy.deepcopy(template), "token_breakdown": {"input": 12}}

    await process_batch([raw_event(doc, 0)], harness.deps(), settings())

    contract = next(iter(harness.archive.effects.values())).contract
    assert isinstance(contract, TelemetryEvent)
    assert contract.token_breakdown is not None
    assert contract.token_breakdown.input == 12
    assert contract.token_breakdown.output is None
    assert contract.token_breakdown.cached is None
    assert contract.token_breakdown.reasoning is None


async def test_missing_optional_cost_fields_stay_null(
    harness: Harness, sandbox_cost: list[Doc]
) -> None:
    doc = copy.deepcopy(sandbox_cost[0])
    for name in ("token_breakdown", "retry_count", "retry_amount", "allocation"):
        doc.pop(name, None)

    await process_batch([raw_event(doc, 0, kind="cost")], harness.deps(), settings())

    contract = next(iter(harness.ledger.effects.values())).contract
    assert isinstance(contract, CostRecord)
    assert contract.token_breakdown is None
    assert contract.retry_count is None
    assert contract.retry_amount is None
    assert contract.allocation is None


@given(data=st.data())
@hyp_settings(max_examples=60, deadline=None)
def test_property_no_telemetry_numeric_field_becomes_zero(data: st.DataObject) -> None:
    from .support import rich_telemetry

    base = rich_telemetry()
    dropped = data.draw(st.sets(st.sampled_from(TELEMETRY_OPTIONAL)))
    keep_parent = base.get("span_kind") in {"delegation", "tool_call"}
    doc = {
        k: copy.deepcopy(v)
        for k, v in base.items()
        if k not in dropped or (keep_parent and k == "parent_span_id")
    }

    event = _normalize(Harness(), doc, "telemetry")

    _assert_no_invented_numbers(event, doc)
    dumped = event.contract.model_dump(mode="json")
    for name in dropped:
        assert dumped.get(name) is None, name


@given(data=st.data())
@hyp_settings(max_examples=60, deadline=None)
def test_property_no_cost_numeric_field_becomes_zero(data: st.DataObject) -> None:
    from .support import rich_cost

    base = rich_cost()
    dropped = data.draw(st.sets(st.sampled_from(COST_OPTIONAL)))
    doc = {k: copy.deepcopy(v) for k, v in base.items() if k not in dropped}

    event = _normalize(Harness(), doc, "cost")

    _assert_no_invented_numbers(event, doc)
    dumped = event.contract.model_dump(mode="json")
    for name in dropped:
        assert dumped.get(name) is None, name
