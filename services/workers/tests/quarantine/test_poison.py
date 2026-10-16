"""Poison isolation end to end with the REAL blob sink: 3 attempts, quarantine, partition flows."""

from __future__ import annotations

import json

import pytest
from azure.core.exceptions import HttpResponseError
from neurosphere_core.errors import DependencyTransientError, InvalidSchemaError
from neurosphere_workers.ingestion.models import QuarantineRecord, compute_doc_id
from neurosphere_workers.ingestion.pipeline import process_batch
from neurosphere_workers.ingestion.reasons import QuarantineReason
from neurosphere_workers.quarantine import BlobQuarantineSink

from .support import (
    T0,
    Doc,
    FakeBlobContainer,
    Harness,
    blob_sink,
    raw_event,
    settings,
    telemetry_at,
)


async def test_poison_lands_in_blob_and_next_event_flows(
    harness: Harness, container: FakeBlobContainer, template: Doc
) -> None:
    poison = telemetry_at(template, "evt-poison", T0)
    healthy = telemetry_at(template, "evt-healthy", T0)
    harness.archive.fail_transient(3)
    deps = harness.deps()
    deps.quarantine = blob_sink(container)

    result = await process_batch([raw_event(poison, 0), raw_event(healthy, 1)], deps, settings())

    poison_id = compute_doc_id(poison["customer_id"], poison["source_id"], "evt-poison")
    healthy_id = compute_doc_id(healthy["customer_id"], healthy["source_id"], "evt-healthy")
    assert container.names("records/") == [f"records/{poison_id}.json"]
    stored = QuarantineRecord.model_validate_json(container.blobs[f"records/{poison_id}.json"])
    assert stored.reason is QuarantineReason.RETRY_BUDGET_EXHAUSTED
    assert stored.attempts == 3
    assert (stored.partition_id, stored.offset) == ("0", "0")
    assert list(harness.ledger.effects) == [healthy_id]
    assert result.accepted == 1
    assert result.quarantined == {QuarantineReason.RETRY_BUDGET_EXHAUSTED: 1}
    # The batch returned, so the checkpoint (past the quarantine write) may be committed.
    assert result.checkpoint == "0:1"
    meta = container.meta[f"records/{poison_id}.json"]
    assert meta["reason"] == "retry_budget_exhausted"
    assert meta["customer_id"] == poison["customer_id"]


async def test_quarantine_write_failure_blocks_the_checkpoint(
    harness: Harness, container: FakeBlobContainer, template: Doc
) -> None:
    harness.archive.fail_transient(3)
    container.fail_status = 503
    deps = harness.deps()
    deps.quarantine = blob_sink(container)

    with pytest.raises(DependencyTransientError):
        await process_batch([raw_event(telemetry_at(template, "e", T0), 0)], deps, settings())


async def test_first_write_wins_and_repeat_is_success(
    harness: Harness, container: FakeBlobContainer, template: Doc
) -> None:
    await _quarantine(harness, container, telemetry_at(template, "evt-a", T0))
    (name,) = container.names("records/")
    first = container.blobs[name]

    await _quarantine(Harness(), container, telemetry_at(template, "evt-a", T0))

    assert container.upload_calls == 2
    assert container.names("records/") == [name]
    assert container.blobs[name] == first


async def _quarantine(harness: Harness, container: FakeBlobContainer, doc: Doc) -> None:
    harness.archive.fail_transient(3)
    deps = harness.deps()
    deps.quarantine = blob_sink(container)
    await process_batch([raw_event(doc, 0)], deps, settings())


async def test_sink_refuses_a_record_with_body_fields(container: FakeBlobContainer) -> None:
    good = QuarantineRecord(
        doc_id="d" * 64,
        reason=QuarantineReason.INVALID_SCHEMA,
        attempts=1,
        partition_id="0",
        offset="1",
        sequence_number=1,
        enqueued_time=T0,
        quarantined_at=T0,
        payload={"customer_id": "c"},
    )
    bad = good.model_construct(**{**good.__dict__, "payload": {"prompt": "synthetic secret"}})

    with pytest.raises(InvalidSchemaError) as info:
        await BlobQuarantineSink(container).write(bad)

    assert info.value.reason == "body_field_present"
    assert not container.blobs


async def test_non_transient_blob_error_is_not_retried(container: FakeBlobContainer) -> None:
    record = QuarantineRecord(
        doc_id="e" * 64,
        reason=QuarantineReason.INVALID_WIRE,
        attempts=1,
        partition_id="0",
        offset="1",
        sequence_number=1,
        enqueued_time=T0,
        quarantined_at=T0,
        payload_sha256="0" * 64,
        payload_bytes=3,
    )
    container.fail_status = 403

    with pytest.raises(HttpResponseError):
        await BlobQuarantineSink(container).write(record)


async def test_unparseable_body_is_stored_as_hash_only(
    harness: Harness, container: FakeBlobContainer
) -> None:
    from .support import raw_from_bytes

    deps = harness.deps()
    deps.quarantine = blob_sink(container)
    await process_batch([raw_from_bytes(b"{not json prompt: hi", 0)], deps, settings())

    (name,) = container.names("records/")
    data = json.loads(container.blobs[name])
    assert data["payload"] is None
    assert data["payload_sha256"]
    assert b"prompt" not in container.blobs[name]
