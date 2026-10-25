"""The archive-backed TraceEventSource / RecordSource over a fake blob container."""

from __future__ import annotations

import gzip
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

from ingestion.support import sandbox_bundle  # type: ignore[import-not-found]
from neurosphere_workers.ingestion.models import compute_doc_id
from neurosphere_workers.runtime.archive_reader import (
    ArchiveReader,
    ArchiveRecordSource,
    ArchiveTraceEventSource,
)


class FakeContainer:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.lists = 0
        self.downloads = 0

    def put(self, name: str, doc: Any) -> None:
        self.blobs[name] = gzip.compress(json.dumps(doc).encode("utf-8"))

    async def list_blobs(self, name_starts_with: str | None = None, **_: Any) -> AsyncIterator[Any]:
        self.lists += 1
        for name in sorted(self.blobs):
            if name_starts_with is None or name.startswith(name_starts_with):
                yield SimpleNamespace(name=name)

    async def download_blob(self, blob: str, **_: Any) -> Any:
        self.downloads += 1

        async def readall() -> bytes:
            return self.blobs[blob]

        return SimpleNamespace(readall=readall)


def _archive(container: FakeContainer, customer: str, doc: dict[str, Any]) -> str:
    doc_id = compute_doc_id(customer, doc["source_id"], doc["event_id"])
    name = f"{customer}/{doc['domain_id'] or '_none'}/2026/10/19/{doc_id}.json.gz"
    container.put(
        name, {"message": {"kind": "telemetry", "customer_id": customer}, "contract": doc}
    )
    return doc_id


def _telemetry() -> dict[str, Any]:
    telemetry, _ = sandbox_bundle()
    return telemetry[0]


async def test_get_event_finds_the_blob_by_doc_id_and_caches_it() -> None:
    doc = _telemetry()
    customer = doc["customer_id"]
    container = FakeContainer()
    doc_id = _archive(container, customer, doc)
    source = ArchiveTraceEventSource(ArchiveReader(container))

    loaded = await source.get_event(customer, doc_id)

    assert loaded is not None
    assert loaded.doc_id == doc_id
    assert loaded.event.event_id.root == doc["event_id"]
    lists, downloads = container.lists, container.downloads
    assert await source.get_event(customer, doc_id) is loaded
    assert (container.lists, container.downloads) == (lists, downloads)  # served from cache


async def test_unknown_doc_id_is_none_and_relisting_is_throttled() -> None:
    doc = _telemetry()
    customer = doc["customer_id"]
    container = FakeContainer()
    _archive(container, customer, doc)
    now = [100.0]
    source = ArchiveTraceEventSource(
        ArchiveReader(container, refresh_seconds=10.0, clock=lambda: now[0])
    )

    assert await source.get_event(customer, "f" * 64) is None
    first = container.lists
    assert await source.get_event(customer, "e" * 64) is None
    assert container.lists == first  # inside the refresh window: no second listing
    now[0] += 11.0
    assert await source.get_event(customer, "e" * 64) is None
    assert container.lists == first + 1


async def test_another_customers_blob_is_never_returned() -> None:
    doc = _telemetry()
    container = FakeContainer()
    doc_id = _archive(container, doc["customer_id"], doc)
    source = ArchiveTraceEventSource(ArchiveReader(container))

    assert await source.get_event("other-customer", doc_id) is None
    # A blob filed under the asked customer's prefix but belonging to another one is refused.
    name = f"other-customer/_none/2026/10/19/{doc_id}.json.gz"
    container.put(
        name,
        {"message": {"kind": "telemetry", "customer_id": doc["customer_id"]}, "contract": doc},
    )
    assert await source.get_event("other-customer", doc_id) is None


async def test_unsafe_customer_segment_reads_nothing() -> None:
    container = FakeContainer()
    source = ArchiveTraceEventSource(ArchiveReader(container))
    assert await source.get_event("../x", "a" * 64) is None
    assert container.lists == 0


async def test_cost_records_are_not_trace_events() -> None:
    _, cost = sandbox_bundle()
    customer = cost[0]["customer_id"]
    container = FakeContainer()
    doc_id = compute_doc_id(customer, cost[0]["source_id"], cost[0]["cost_id"])
    container.put(
        f"{customer}/_none/2026/10/19/{doc_id}.json.gz",
        {"message": {"kind": "cost", "customer_id": customer}, "contract": cost[0]},
    )
    assert (
        await ArchiveTraceEventSource(ArchiveReader(container)).get_event(customer, doc_id) is None
    )


async def test_record_source_yields_the_customers_records_only() -> None:
    doc = _telemetry()
    customer = doc["customer_id"]
    container = FakeContainer()
    doc_id = _archive(container, customer, doc)
    container.put(
        "elsewhere/_none/2026/10/19/" + "a" * 64 + ".json.gz",
        {"message": {"kind": "telemetry", "customer_id": "elsewhere"}, "contract": doc},
    )
    records = [r async for r in ArchiveRecordSource(ArchiveReader(container), customer).records()]
    assert [r["doc_id"] for r in records] == [doc_id]
