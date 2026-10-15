"""Dedupe on (customer_id, source_id, event_id): first write wins, repeats are counted."""

from __future__ import annotations

from neurosphere_workers.ingestion.models import compute_doc_id
from neurosphere_workers.ingestion.pipeline import process_batch

from .support import T0, Doc, Harness, raw_event, settings, telemetry_at


async def test_same_event_twice_in_one_batch(harness: Harness, template: Doc) -> None:
    doc = telemetry_at(template, "evt-dup-1", T0)
    batch = [raw_event(doc, 0), raw_event(doc, 1)]

    result = await process_batch(batch, harness.deps(), settings())

    assert (result.accepted, result.duplicates) == (1, 1)
    assert len(harness.archive.effects) == 1
    assert len(harness.ledger.effects) == 1
    assert harness.archive.write_calls == 1
    assert result.checkpoint == "0:1"


async def test_duplicate_across_restart_with_same_stores(harness: Harness, template: Doc) -> None:
    doc = telemetry_at(template, "evt-dup-2", T0)
    first = await process_batch([raw_event(doc, 0)], harness.deps(), settings())

    # "Restart": a brand-new deps object and settings, but the same durable stores.
    second = await process_batch([raw_event(doc, 5)], harness.deps(), settings())

    assert (first.accepted, first.duplicates) == (1, 0)
    assert (second.accepted, second.duplicates) == (0, 1)
    assert len(harness.archive.effects) == 1
    assert len(harness.ledger.effects) == 1
    assert harness.archive.write_calls == 1
    assert harness.ledger.write_calls == 1


async def test_doc_id_is_sha256_of_identity(harness: Harness, template: Doc) -> None:
    doc = telemetry_at(template, "evt-id-1", T0)
    await process_batch([raw_event(doc, 0)], harness.deps(), settings())

    expected = compute_doc_id(doc["customer_id"], doc["source_id"], "evt-id-1")
    assert list(harness.archive.effects) == [expected]
    assert len(expected) == 64


async def test_same_event_id_in_another_source_is_not_a_duplicate(
    harness: Harness, template: Doc
) -> None:
    a = telemetry_at(template, "evt-shared", T0)
    b = {**a, "source_id": "another-source"}

    result = await process_batch([raw_event(a, 0), raw_event(b, 1)], harness.deps(), settings())

    assert (result.accepted, result.duplicates) == (2, 0)
    assert len(harness.archive.effects) == 2


async def test_cost_records_dedupe_by_cost_id(harness: Harness, sandbox_cost: list[Doc]) -> None:
    cost = sandbox_cost[0]
    batch = [raw_event(cost, 0, kind="cost"), raw_event(cost, 1, kind="cost")]

    result = await process_batch(batch, harness.deps(), settings())

    assert (result.accepted, result.duplicates) == (1, 1)
    assert len(harness.ledger.effects) == 1
