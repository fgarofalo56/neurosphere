"""Read side of the redacted archive for the workers (blob container, one cloud/account).

The PRP-07 archive writes ``{customer}/{domain or _none}/{yyyy}/{mm}/{dd}/{doc_id}.json.gz`` (a
gzip of the redacted ``NormalizedEvent`` dump). An outbox entry only carries the ``doc_id``, so
``ArchiveTraceEventSource`` indexes the customer's blob names (one listing, cached, refreshed at
most once per ``refresh_seconds`` on a miss) and downloads the one blob. The listing is bounded by
``max_blobs``: sizing it against a real account is an OPEN gate (G07/G12), not claimed here.

Everything returned is already redacted telemetry (bodies dropped, people pseudonymized); a
record for a different customer than asked is never returned.
"""

from __future__ import annotations

import gzip
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from typing import Any, Final, Protocol

from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.errors import DependencyTransientError

from neurosphere_workers.projections.catalog.source import MAX_CHILD_SPANS, LoadedEvent

__all__ = ["ArchiveReader", "ArchiveRecordSource", "ArchiveTraceEventSource", "BlobReadable"]

logger = logging.getLogger("neurosphere.workers.runtime")

BLOB_SUFFIX: Final = ".json.gz"
_SAFE_SEGMENT: Final = re.compile(r"[^/\\\x00-\x1f]+")
DEFAULT_MAX_BLOBS: Final = 20_000
DEFAULT_MAX_SCAN: Final = 500
_CACHE_EVENTS: Final = 2_048


class BlobReadable(Protocol):
    """The slice of the aio ``ContainerClient`` this module uses."""

    def list_blobs(
        self, name_starts_with: str | None = None, **kwargs: Any
    ) -> AsyncIterator[Any]: ...

    def download_blob(self, blob: str, **kwargs: Any) -> Awaitable[Any]: ...


def _segment_ok(value: str) -> bool:
    return bool(_SAFE_SEGMENT.fullmatch(value)) and value not in {".", ".."}


class ArchiveReader:
    """Name index plus blob download/decode for one container."""

    def __init__(
        self,
        container: BlobReadable,
        *,
        max_blobs: int = DEFAULT_MAX_BLOBS,
        refresh_seconds: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._container = container
        self._max_blobs = max_blobs
        self._refresh = refresh_seconds
        self._clock = clock
        self._index: dict[str, dict[str, str]] = {}  # customer -> doc_id -> blob name
        self._refreshed: dict[str, float] = {}
        self.truncated = False

    async def _list(self, customer_id: str) -> dict[str, str]:
        prefix = f"{customer_id}/"
        found: dict[str, str] = {}
        try:
            async for blob in self._container.list_blobs(name_starts_with=prefix):
                name = str(blob.name)
                if not name.endswith(BLOB_SUFFIX):
                    continue  # manifests and anything that is not an archive record
                if len(found) >= self._max_blobs:
                    self.truncated = True
                    break
                found[name.rsplit("/", 1)[-1][: -len(BLOB_SUFFIX)]] = name
        except Exception as exc:
            raise DependencyTransientError(
                "archive storage unavailable", reason="archive_storage"
            ) from exc
        return found

    async def names(self, customer_id: str, *, force: bool = False) -> Mapping[str, str]:
        """``doc_id -> blob name`` for ``customer_id`` (cached; relisted when ``force``)."""
        if not _segment_ok(customer_id):
            return {}
        now = self._clock()
        last = self._refreshed.get(customer_id)
        if force and last is not None and now - last < self._refresh:
            force = False  # throttle: a miss relists at most once per refresh window
        if customer_id not in self._index or force:
            self._index[customer_id] = await self._list(customer_id)
            self._refreshed[customer_id] = now
        return self._index[customer_id]

    async def read(self, customer_id: str, blob_name: str) -> dict[str, Any] | None:
        """The decoded archive record, or ``None`` when unreadable or another customer's."""
        try:
            stream = await self._container.download_blob(blob_name)
            raw = await stream.readall()
        except Exception as exc:
            raise DependencyTransientError(
                "archive storage unavailable", reason="archive_storage"
            ) from exc
        try:
            doc = json.loads(gzip.decompress(raw))
        except (OSError, EOFError, ValueError):
            return None
        if not isinstance(doc, dict):
            return None
        message = doc.get("message")
        if not isinstance(message, dict) or message.get("customer_id") != customer_id:
            return None
        return doc


def _telemetry(doc: Mapping[str, Any], doc_id: str) -> LoadedEvent | None:
    message = doc.get("message")
    contract = doc.get("contract")
    if not isinstance(message, dict) or message.get("kind") != "telemetry":
        return None
    try:
        return LoadedEvent(doc_id, TelemetryEvent.model_validate(contract))
    except ValueError:
        logger.warning("archived telemetry failed validation", extra={"event": "archive.invalid"})
        return None


class ArchiveTraceEventSource:
    """``TraceEventSource`` over the archive. Scoped to the customer on every call."""

    def __init__(self, reader: ArchiveReader, *, max_scan: int = DEFAULT_MAX_SCAN) -> None:
        self._reader = reader
        self._max_scan = max_scan
        self._events: dict[tuple[str, str], LoadedEvent | None] = {}

    def _remember(self, customer_id: str, doc_id: str, loaded: LoadedEvent | None) -> None:
        if len(self._events) >= _CACHE_EVENTS:
            oldest = next(iter(self._events))  # dict: insertion order
            del self._events[oldest]
        self._events[(customer_id, doc_id)] = loaded

    async def get_event(self, customer_id: str, doc_id: str) -> LoadedEvent | None:
        key = (customer_id, doc_id)
        if key in self._events and self._events[key] is not None:
            return self._events[key]
        names = await self._reader.names(customer_id)
        name = names.get(doc_id)
        if name is None:
            name = (await self._reader.names(customer_id, force=True)).get(doc_id)
        if name is None:
            return None
        doc = await self._reader.read(customer_id, name)
        loaded = None if doc is None else _telemetry(doc, doc_id)
        if loaded is not None:
            self._remember(customer_id, doc_id, loaded)
        return loaded

    async def _recent(self, customer_id: str) -> list[LoadedEvent]:
        names = await self._reader.names(customer_id, force=True)
        ordered = sorted(names.items(), key=lambda kv: kv[1], reverse=True)[: self._max_scan]
        out: list[LoadedEvent] = []
        for doc_id, name in ordered:
            cached = self._events.get((customer_id, doc_id))
            if cached is None:
                doc = await self._reader.read(customer_id, name)
                cached = None if doc is None else _telemetry(doc, doc_id)
                if cached is not None:
                    self._remember(customer_id, doc_id, cached)
            if cached is not None:
                out.append(cached)
        return out

    async def find_span(self, customer_id: str, trace_id: str, span_id: str) -> LoadedEvent | None:
        for loaded in await self._recent(customer_id):
            event = loaded.event
            if (
                event.trace_id is not None
                and event.trace_id.root == trace_id
                and event.span_id is not None
                and event.span_id.root == span_id
            ):
                return loaded
        return None

    async def find_child_spans(
        self, customer_id: str, trace_id: str, parent_span_id: str
    ) -> Sequence[LoadedEvent]:
        found = [
            loaded
            for loaded in await self._recent(customer_id)
            if loaded.event.trace_id is not None
            and loaded.event.trace_id.root == trace_id
            and loaded.event.parent_span_id is not None
            and loaded.event.parent_span_id.root == parent_span_id
        ]
        return sorted(found, key=lambda loaded: loaded.doc_id)[:MAX_CHILD_SPANS]


class ArchiveRecordSource:
    """``RecordSource`` (evaluation sampler input): archive records of one customer, bounded."""

    def __init__(
        self, reader: ArchiveReader, customer_id: str, *, max_records: int = 5_000
    ) -> None:
        self._reader = reader
        self._customer = customer_id
        self._max = max_records

    async def records(self) -> AsyncIterator[Mapping[str, Any]]:
        names = await self._reader.names(self._customer, force=True)
        for doc_id in sorted(names)[: self._max]:
            doc = await self._reader.read(self._customer, names[doc_id])
            if doc is not None:
                yield {**doc, "doc_id": doc.get("doc_id", doc_id)}
