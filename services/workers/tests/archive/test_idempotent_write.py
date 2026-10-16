"""The same event twice yields one blob; transient storage errors are retryable."""

from __future__ import annotations

import hashlib

import pytest
from neurosphere_core.errors import DependencyTransientError
from neurosphere_workers.ingestion.pipeline import PipelineDeps, process_batch

from .support import (
    T0,
    Doc,
    FakeContainer,
    make_event,
    make_sink,
    raw_event,
    read_blob,
    settings,
    telemetry_at,
)


async def test_same_event_twice_is_one_blob(template: Doc, container: FakeContainer) -> None:
    sink = make_sink(container)
    event = await make_event(template, "evt-i1", T0)
    await sink.write(event)
    first = dict(container.blobs)
    await sink.write(event)

    assert container.upload_calls == 2
    assert container.blobs == first
    assert len(container.blobs) == 1


async def test_content_hash_metadata_matches_blob(template: Doc, container: FakeContainer) -> None:
    event = await make_event(template, "evt-i2", T0)
    await make_sink(container).write(event)
    ((name, data),) = container.blobs.items()
    assert container.metas[name]["sha256"] == hashlib.sha256(data).hexdigest()
    assert read_blob(data)["doc_id"] == event.doc_id


async def test_two_sinks_same_event_one_blob(template: Doc, container: FakeContainer) -> None:
    event = await make_event(template, "evt-i3", T0)
    await make_sink(container).write(event)
    await make_sink(container).write(event)
    assert len(container.blobs) == 1


async def test_process_batch_redelivery(template: Doc, container: FakeContainer) -> None:
    from neurosphere_workers.ingestion.fakes import (
        FakeLedgerSink,
        FakeMarkerStore,
        FakeQuarantineSink,
        FakeWatermarkStore,
    )

    deps = PipelineDeps(
        quarantine=FakeQuarantineSink(),
        archive=make_sink(container),
        ledger=FakeLedgerSink(),
        markers=FakeMarkerStore(),
        watermarks=FakeWatermarkStore(),
        cloud="commercial",
    )
    doc = telemetry_at(template, "evt-i4", T0)
    first = await process_batch([raw_event(doc, 0)], deps, settings())
    second = await process_batch([raw_event(doc, 5)], deps, settings())

    assert (first.accepted, second.duplicates) == (1, 1)
    assert len(container.blobs) == 1

    # Crash recovery: a fresh marker store (marker lost) redelivers; the archive stays at one.
    deps2 = PipelineDeps(
        quarantine=FakeQuarantineSink(),
        archive=make_sink(container),
        ledger=FakeLedgerSink(),
        markers=FakeMarkerStore(),
        watermarks=FakeWatermarkStore(),
        cloud="commercial",
    )
    third = await process_batch([raw_event(doc, 9)], deps2, settings())
    assert third.accepted == 1
    assert len(container.blobs) == 1


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_retryable_status_is_transient(
    template: Doc, container: FakeContainer, status: int
) -> None:
    event = await make_event(template, "evt-i5", T0)
    container.fail_status = status
    with pytest.raises(DependencyTransientError):
        await make_sink(container).write(event)


async def test_other_errors_are_a_crash(template: Doc, container: FakeContainer) -> None:
    from azure.core.exceptions import HttpResponseError

    event = await make_event(template, "evt-i6", T0)
    container.fail_status = 403
    with pytest.raises(HttpResponseError):
        await make_sink(container).write(event)
