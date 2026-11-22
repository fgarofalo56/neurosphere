"""ResolvingTraceEventSource and ResolvingRecordSource (PRP-137 item 2)."""

from __future__ import annotations

import copy
import importlib.util
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from neurosphere_core.errors import DependencyTransientError
from neurosphere_workers.agent_identity import ResolvingRecordSource, ResolvingTraceEventSource
from neurosphere_workers.evaluation.source import InMemoryRecordSource
from neurosphere_workers.projections.catalog import InMemoryTraceEventSource, LoadedEvent

from .fakes import CUSTOMER, TRACE, StubLookup, doc, loaded, make_resolver

_PATH = Path(__file__).resolve().parents[4] / "tests" / "contracts" / "validators.py"
_SPEC = importlib.util.spec_from_file_location("ns_contract_validators_prp137_workers", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
sys.path.insert(0, str(_PATH.parent))
try:
    _SPEC.loader.exec_module(_MOD)
finally:
    sys.path.remove(str(_PATH.parent))
validate_canonical_id_grammar = _MOD.validate_canonical_id_grammar

ALIAS_TARGET = f"commercial:{CUSTOMER}:foundry:agent:aliased"
OWNED = f"commercial:{CUSTOMER}:sandbox:agent:a-1"


def _grammar_ok(value: str) -> bool:
    return validate_canonical_id_grammar({"canonical_agent_id": value}) == []


def _source(*events: LoadedEvent) -> InMemoryTraceEventSource:
    return InMemoryTraceEventSource(events)


async def test_alias_stamps_only_the_agent_fields() -> None:
    original = loaded("d1", doc("e1"))
    before = original.event.model_dump(mode="json")
    lookup = StubLookup({"ext-1": ALIAS_TARGET})
    source = ResolvingTraceEventSource(_source(original), make_resolver(lookup))

    got = await source.get_event(CUSTOMER, "d1")

    assert got is not None
    assert got.doc_id == "d1"
    assert got.agent_resolution == "alias"
    assert got.event.canonical_agent_id is not None
    assert got.event.canonical_agent_id.root == ALIAS_TARGET
    after = got.event.model_dump(mode="json")
    assert {k: v for k, v in after.items() if k != "canonical_agent_id"} == {
        k: v for k, v in before.items() if k != "canonical_agent_id"
    }
    # the inner object is untouched
    assert original.event.canonical_agent_id is None
    assert original.agent_resolution is None
    assert original.event.model_dump(mode="json") == before


async def test_derived_is_stamped_and_passes_the_grammar() -> None:
    source = ResolvingTraceEventSource(
        _source(loaded("d1", doc("e1"))), make_resolver(StubLookup())
    )
    got = await source.get_event(CUSTOMER, "d1")
    assert got is not None
    assert got.agent_resolution == "derived"
    assert got.event.canonical_agent_id is not None
    assert _grammar_ok(got.event.canonical_agent_id.root)
    assert got.event.canonical_agent_id.root.startswith(f"commercial:{CUSTOMER}:")


async def test_declared_keeps_an_owned_canonical_id() -> None:
    event = loaded("d1", doc("e1", canonical_agent_id=OWNED))
    source = ResolvingTraceEventSource(_source(event), make_resolver(StubLookup()))
    got = await source.get_event(CUSTOMER, "d1")
    assert got is not None
    assert got.agent_resolution == "declared"
    assert got.event.canonical_agent_id is not None
    assert got.event.canonical_agent_id.root == OWNED


async def test_no_external_id_is_none() -> None:
    event = loaded("d1", doc("e1", external_agent_id=None))
    source = ResolvingTraceEventSource(_source(event), make_resolver(StubLookup()))
    got = await source.get_event(CUSTOMER, "d1")
    assert got is not None
    assert got.agent_resolution == "none"
    assert got.event.canonical_agent_id is None


async def test_unknown_event_is_none() -> None:
    source = ResolvingTraceEventSource(_source(), make_resolver(StubLookup()))
    assert await source.get_event(CUSTOMER, "nope") is None
    assert await source.find_span(CUSTOMER, TRACE, "0" * 16) is None
    assert list(await source.find_child_spans(CUSTOMER, TRACE, "0" * 16)) == []


async def test_find_span_stamps() -> None:
    event = loaded("d1", doc("e1"))
    lookup = StubLookup({"ext-1": ALIAS_TARGET})
    source = ResolvingTraceEventSource(_source(event), make_resolver(lookup))
    got = await source.find_span(CUSTOMER, TRACE, "f6c75e5fa45fb230")
    assert got is not None
    assert got.agent_resolution == "alias"


async def test_child_spans_stamp_every_event_with_one_lookup_per_distinct_agent() -> None:
    parent_span = "aaaaaaaaaaaaaaaa"
    kids = [
        loaded(
            f"k{i}",
            doc(f"ek{i}", span_id=f"{i:016x}", parent_span_id=parent_span, external_agent_id=ext),
        )
        for i, ext in enumerate(["ext-1", "ext-1", "ext-2"], start=1)
    ]
    lookup = StubLookup({"ext-1": ALIAS_TARGET})
    source = ResolvingTraceEventSource(_source(*kids), make_resolver(lookup))

    got = await source.find_child_spans(CUSTOMER, TRACE, parent_span)

    assert [g.doc_id for g in got] == ["k1", "k2", "k3"]
    assert [g.agent_resolution for g in got] == ["alias", "alias", "derived"]
    assert all(k.event.canonical_agent_id is None for k in kids)
    assert sorted(c.alias_value for c in lookup.calls) == ["ext-1", "ext-2"]


async def test_lookup_failure_is_transient_and_chained() -> None:
    lookup = StubLookup()
    lookup.error = RuntimeError("cosmos down")
    source = ResolvingTraceEventSource(_source(loaded("d1", doc("e1"))), make_resolver(lookup))
    with pytest.raises(DependencyTransientError) as raised:
        await source.get_event(CUSTOMER, "d1")
    assert raised.value.retryable is True
    assert isinstance(raised.value.__cause__, RuntimeError)


def _record(event_id: str, **overrides: Any) -> dict[str, Any]:
    return {
        "doc_id": event_id,
        "message": {"kind": "telemetry", "customer_id": CUSTOMER},
        "contract": doc(event_id, **overrides),
    }


async def _collect(source: ResolvingRecordSource) -> list[Mapping[str, Any]]:
    return [record async for record in source.records()]


async def test_record_source_copies_and_never_mutates() -> None:
    record = _record("e1")
    snapshot = copy.deepcopy(record)
    lookup = StubLookup({"ext-1": ALIAS_TARGET})
    source = ResolvingRecordSource(InMemoryRecordSource([record]), make_resolver(lookup))

    out = await _collect(source)

    assert len(out) == 1
    assert out[0]["contract"]["canonical_agent_id"] == ALIAS_TARGET
    assert out[0]["doc_id"] == "e1"
    assert out[0]["message"] == record["message"]
    assert out[0] is not record
    assert out[0]["contract"] is not record["contract"]
    assert record == snapshot


async def test_record_source_derived_and_none() -> None:
    records = [_record("e1"), _record("e2", external_agent_id=None)]
    source = ResolvingRecordSource(InMemoryRecordSource(records), make_resolver(StubLookup()))
    out = await _collect(source)
    derived = out[0]["contract"]["canonical_agent_id"]
    assert isinstance(derived, str) and _grammar_ok(derived)
    assert out[1]["contract"]["canonical_agent_id"] is None


async def test_non_telemetry_records_pass_through_unchanged() -> None:
    cost = {"doc_id": "c1", "message": {"kind": "cost"}, "contract": {"amount": 1.5}}
    bare = {"doc_id": "b1", "message": {"kind": "cost"}}
    source = ResolvingRecordSource(InMemoryRecordSource([cost, bare]), make_resolver(StubLookup()))
    out = await _collect(source)
    assert out[0] is cost
    assert out[1] is bare


async def test_record_lookup_failure_is_transient() -> None:
    lookup = StubLookup()
    lookup.error = RuntimeError("down")
    source = ResolvingRecordSource(InMemoryRecordSource([_record("e1")]), make_resolver(lookup))
    with pytest.raises(DependencyTransientError):
        await _collect(source)
