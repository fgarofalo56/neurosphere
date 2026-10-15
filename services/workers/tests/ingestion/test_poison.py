"""Bounded retries (C8): 3 attempts, then quarantine; a poison event never blocks the partition."""

from __future__ import annotations

from neurosphere_workers.ingestion.models import compute_doc_id
from neurosphere_workers.ingestion.pipeline import process_batch
from neurosphere_workers.ingestion.reasons import QuarantineReason

from .support import T0, Doc, Harness, raw_event, settings, telemetry_at


async def test_transient_failure_three_times_is_quarantined_and_next_event_flows(
    harness: Harness, template: Doc
) -> None:
    poison = telemetry_at(template, "evt-poison", T0)
    healthy = telemetry_at(template, "evt-healthy", T0)
    harness.archive.fail_transient(3)

    result = await process_batch(
        [raw_event(poison, 0), raw_event(healthy, 1)], harness.deps(), settings()
    )

    poison_id = compute_doc_id(poison["customer_id"], poison["source_id"], "evt-poison")
    healthy_id = compute_doc_id(healthy["customer_id"], healthy["source_id"], "evt-healthy")
    record = harness.quarantine.effects[poison_id]
    assert record.reason is QuarantineReason.RETRY_BUDGET_EXHAUSTED
    assert record.attempts == 3
    assert (record.partition_id, record.offset) == ("0", "0")
    assert list(harness.archive.effects) == [healthy_id]
    assert list(harness.ledger.effects) == [healthy_id]
    assert (result.accepted, result.quarantined) == (
        1,
        {QuarantineReason.RETRY_BUDGET_EXHAUSTED: 1},
    )
    assert result.checkpoint == "0:1"
    assert len(harness.sleeps) == 2  # backoff between the 3 attempts


async def test_poison_event_is_not_marked_accepted(harness: Harness, template: Doc) -> None:
    poison = telemetry_at(template, "evt-poison2", T0)
    harness.ledger.fail_for(
        compute_doc_id(poison["customer_id"], poison["source_id"], "evt-poison2")
    )

    await process_batch([raw_event(poison, 0)], harness.deps(), settings())

    assert not harness.markers.marked  # a later replay must still be able to accept it
    assert harness.ledger.write_calls == 3


async def test_transient_failure_recovering_within_budget_is_accepted(
    harness: Harness, template: Doc
) -> None:
    harness.ledger.fail_transient(2)

    result = await process_batch(
        [raw_event(telemetry_at(template, "evt-flaky", T0), 0)], harness.deps(), settings()
    )

    assert (result.accepted, result.quarantined_total) == (1, 0)
    assert harness.ledger.write_calls == 3
    assert not harness.quarantine.effects


async def test_attempt_budget_comes_from_settings(harness: Harness, template: Doc) -> None:
    harness.archive.fail_transient(10)

    await process_batch(
        [raw_event(telemetry_at(template, "evt-two", T0), 0)],
        harness.deps(),
        settings(max_attempts=2),
    )

    (record,) = harness.quarantine.effects.values()
    assert record.attempts == 2
    assert harness.archive.write_calls == 2


async def test_poison_quarantine_payload_has_no_bodies(harness: Harness, template: Doc) -> None:
    harness.archive.fail_transient(3)

    await process_batch(
        [raw_event(telemetry_at(template, "evt-p3", T0), 0)], harness.deps(), settings()
    )

    (record,) = harness.quarantine.effects.values()
    assert record.payload is not None
    assert record.payload_sha256 is None
    assert record.event_id == "evt-p3"
