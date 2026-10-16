"""Event-time watermark (C7): late is flagged, never dropped; window from settings."""

from __future__ import annotations

from datetime import timedelta

from neurosphere_workers.ingestion.models import compute_doc_id
from neurosphere_workers.ingestion.pipeline import process_batch

from .support import T0, Doc, Harness, raw_event, settings, telemetry_at


def _late(harness: Harness, doc: Doc) -> bool:
    doc_id = compute_doc_id(doc["customer_id"], doc["source_id"], doc["event_id"])
    return harness.archive.effects[doc_id].late


async def test_out_of_order_inside_window_is_not_late(harness: Harness, template: Doc) -> None:
    newest = telemetry_at(template, "evt-new", T0 + timedelta(minutes=10))
    inside = telemetry_at(template, "evt-in", T0 + timedelta(minutes=10) - timedelta(seconds=299))

    result = await process_batch(
        [raw_event(newest, 0), raw_event(inside, 1)], harness.deps(), settings()
    )

    assert (result.accepted, result.late) == (2, 0)
    assert not _late(harness, inside)


async def test_beyond_window_is_late_but_still_accepted(harness: Harness, template: Doc) -> None:
    newest = telemetry_at(template, "evt-new", T0 + timedelta(minutes=10))
    stale = telemetry_at(template, "evt-stale", T0)

    result = await process_batch(
        [raw_event(newest, 0), raw_event(stale, 1)], harness.deps(), settings()
    )

    assert (result.accepted, result.late) == (2, 1)
    assert _late(harness, stale)
    assert not _late(harness, newest)
    assert len(harness.ledger.effects) == 2  # never dropped


async def test_lateness_window_comes_from_settings(harness: Harness, template: Doc) -> None:
    newest = telemetry_at(template, "evt-new", T0 + timedelta(minutes=10))
    older = telemetry_at(template, "evt-old", T0 + timedelta(minutes=9))

    tight = await process_batch(
        [raw_event(newest, 0), raw_event(older, 1)], harness.deps(), settings(lateness_seconds=30)
    )

    assert tight.late == 1


async def test_watermark_is_per_source(harness: Harness, template: Doc) -> None:
    newest = telemetry_at(template, "evt-a", T0 + timedelta(hours=1))
    other = {**telemetry_at(template, "evt-b", T0), "source_id": "other-source"}

    result = await process_batch(
        [raw_event(newest, 0), raw_event(other, 1)], harness.deps(), settings()
    )

    assert result.late == 0


async def test_watermark_persists_across_batches(harness: Harness, template: Doc) -> None:
    newest = telemetry_at(template, "evt-new", T0 + timedelta(minutes=10))
    stale = telemetry_at(template, "evt-stale", T0)
    await process_batch([raw_event(newest, 0)], harness.deps(), settings())

    result = await process_batch([raw_event(stale, 1)], harness.deps(), settings())

    assert result.late == 1
    key = (template["customer_id"], template["source_id"])
    assert harness.watermarks.values[key] == T0 + timedelta(minutes=10)  # never moves back


async def test_cost_records_use_usage_window_for_event_time(
    harness: Harness, sandbox_cost: list[Doc]
) -> None:
    cost = sandbox_cost[0]

    await process_batch([raw_event(cost, 0, kind="cost")], harness.deps(), settings())

    event = next(iter(harness.ledger.effects.values()))
    assert event.event_time.isoformat().startswith(cost["usage_end"][:19])
