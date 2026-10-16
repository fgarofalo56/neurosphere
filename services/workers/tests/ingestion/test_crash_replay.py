"""Crash rule: marker LAST; redelivery re-runs idempotent sink writes, no double effect."""

from __future__ import annotations

import pytest
from neurosphere_core.errors import DependencyTransientError
from neurosphere_workers.ingestion.fakes import SimulatedCrash
from neurosphere_workers.ingestion.models import EventKey, compute_doc_id
from neurosphere_workers.ingestion.pipeline import process_batch

from .support import T0, Doc, Harness, raw_event, raw_from_bytes, settings, telemetry_at


def _key(doc: Doc) -> EventKey:
    return EventKey(doc["customer_id"], doc["source_id"], doc["event_id"])


async def test_crash_after_archive_before_marker_then_redelivery(
    harness: Harness, template: Doc
) -> None:
    doc = telemetry_at(template, "evt-crash", T0)
    batch = [raw_event(doc, 0)]
    harness.archive.crash_after_next_write()

    with pytest.raises(SimulatedCrash):
        await process_batch(batch, harness.deps(), settings())

    # The archive took the write; nothing downstream happened and the marker is absent.
    assert len(harness.archive.effects) == 1
    assert not harness.ledger.effects
    assert not await harness.markers.is_accepted(_key(doc))

    result = await process_batch(batch, harness.deps(), settings())  # redelivery

    doc_id = compute_doc_id(doc["customer_id"], doc["source_id"], doc["event_id"])
    assert (result.accepted, result.duplicates) == (1, 0)  # not skipped
    assert list(harness.archive.effects) == [doc_id]
    assert list(harness.ledger.effects) == [doc_id]
    assert harness.archive.write_calls == 2  # re-run, but one effect
    assert await harness.markers.is_accepted(_key(doc))


async def test_crash_after_ledger_before_marker_then_redelivery(
    harness: Harness, template: Doc
) -> None:
    doc = telemetry_at(template, "evt-crash2", T0)
    batch = [raw_event(doc, 0)]
    harness.ledger.crash_after_next_write()

    with pytest.raises(SimulatedCrash):
        await process_batch(batch, harness.deps(), settings())
    assert not await harness.markers.is_accepted(_key(doc))

    await process_batch(batch, harness.deps(), settings())

    assert len(harness.archive.effects) == 1
    assert len(harness.ledger.effects) == 1
    assert harness.ledger.write_calls == 2


async def test_crash_mid_batch_keeps_earlier_events_accepted(
    harness: Harness, template: Doc
) -> None:
    docs = [telemetry_at(template, f"evt-mid-{i}", T0) for i in range(3)]
    batch = [raw_event(d, i) for i, d in enumerate(docs)]
    original_accept = harness.ledger.accept
    calls = 0

    async def flaky(event):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SimulatedCrash
        await original_accept(event)

    harness.ledger.accept = flaky  # type: ignore[method-assign]

    with pytest.raises(SimulatedCrash):
        await process_batch(batch, harness.deps(), settings())
    harness.ledger.accept = original_accept  # type: ignore[method-assign]

    result = await process_batch(batch, harness.deps(), settings())

    assert (result.accepted, result.duplicates) == (2, 1)  # event 0 was already marked
    assert len(harness.archive.effects) == 3
    assert len(harness.ledger.effects) == 3


async def test_quarantine_sink_failure_raises_and_yields_no_checkpoint(
    harness: Harness,
) -> None:
    harness.quarantine.fail_transient(1)

    with pytest.raises(DependencyTransientError):
        await process_batch([raw_from_bytes(b"garbage", 0)], harness.deps(), settings())

    assert not harness.quarantine.effects  # nothing durable, so the caller must not checkpoint
