"""Checkpoint-after-success rule for the Event Hubs adapter (C4), with a fake partition context."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from neurosphere_core.errors import DependencyTransientError
from neurosphere_workers.ingestion.consumer import IngestionConsumer, to_raw_message

from .support import T0, Doc, Harness, raw_event, settings, telemetry_at


class FakeEvent:
    def __init__(self, body: bytes, offset: int, enqueued_time: datetime | None = T0) -> None:
        self.body: Any = iter([body[:5], body[5:]])  # SDK bodies are iterables of byte chunks
        self.offset = str(offset)
        self.sequence_number = offset
        self.enqueued_time = enqueued_time


class FakePartitionContext:
    partition_id = "3"

    def __init__(self, on_checkpoint: Callable[[], None] | None = None) -> None:
        self.checkpointed: list[FakeEvent] = []
        self._on_checkpoint = on_checkpoint

    async def update_checkpoint(self, event: Any = None) -> None:
        if self._on_checkpoint is not None:
            self._on_checkpoint()
        self.checkpointed.append(event)


def _consumer(harness: Harness) -> IngestionConsumer:
    return IngestionConsumer(cast(Any, object()), harness.deps(), settings())


def _events(docs: list[Doc]) -> list[FakeEvent]:
    return [FakeEvent(raw_event(d, i).body, i) for i, d in enumerate(docs)]


async def test_checkpoint_follows_success_and_names_the_last_event(
    harness: Harness, template: Doc
) -> None:
    events = _events([telemetry_at(template, f"evt-c{i}", T0) for i in range(3)])
    seen_at_checkpoint: list[int] = []
    ctx = FakePartitionContext(lambda: seen_at_checkpoint.append(len(harness.ledger.effects)))

    result = await _consumer(harness).on_event_batch(ctx, events)

    assert result is not None and result.accepted == 3
    assert ctx.checkpointed == [events[-1]]
    assert seen_at_checkpoint == [3]  # all sinks had written before the checkpoint moved
    assert result.checkpoint == "3:2"


async def test_no_checkpoint_when_processing_raises(harness: Harness) -> None:
    harness.quarantine.fail_transient(1)
    ctx = FakePartitionContext()

    with pytest.raises(DependencyTransientError):
        await _consumer(harness).on_event_batch(ctx, [FakeEvent(b"garbage-bytes", 0)])

    assert ctx.checkpointed == []


async def test_no_checkpoint_when_a_sink_crashes(harness: Harness, template: Doc) -> None:
    harness.archive.crash_after_next_write()
    ctx = FakePartitionContext()
    events = _events([telemetry_at(template, "evt-crash", T0)])

    from neurosphere_workers.ingestion.fakes import SimulatedCrash

    with pytest.raises(SimulatedCrash):
        await _consumer(harness).on_event_batch(ctx, events)

    assert ctx.checkpointed == []


async def test_quarantined_batch_still_checkpoints_after_the_quarantine_write(
    harness: Harness,
) -> None:
    ctx = FakePartitionContext(lambda: None)

    result = await _consumer(harness).on_event_batch(ctx, [FakeEvent(b"garbage-bytes", 7)])

    assert result is not None and result.quarantined_total == 1
    assert len(harness.quarantine.effects) == 1
    assert len(ctx.checkpointed) == 1


async def test_empty_batch_does_not_checkpoint(harness: Harness) -> None:
    ctx = FakePartitionContext()

    assert await _consumer(harness).on_event_batch(ctx, []) is None

    assert ctx.checkpointed == []


def test_to_raw_message_joins_body_chunks_and_tolerates_missing_enqueued_time() -> None:
    raw = to_raw_message(FakeEvent(b"0123456789", 9, enqueued_time=None), "2")

    assert raw.body == b"0123456789"
    assert (raw.partition_id, raw.offset, raw.sequence_number) == ("2", "9", 9)
    assert raw.enqueued_time.tzinfo is UTC
