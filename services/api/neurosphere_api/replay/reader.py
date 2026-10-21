"""Scope-checked trace readers for replay (PRP-18 item 5). Read-only; stored, redacted data only.

* :class:`TraceReader` -- the protocol the router depends on. Every call carries the customer id
  derived from the caller's ``IdentityScope`` and the addressed domain; an implementation must
  return nothing for another customer. It MAY return spans of other domains of the same
  customer (the assembler drops and reports them); it must never return another customer's.
* :class:`InMemoryTraceReader` -- tests and the synthetic sandbox.
* :class:`ArchiveTraceReader` -- reads the PRP-07 redacted, pseudonymized archive blobs
  (``{customer}/{domain or _none}/{yyyy}/{mm}/{dd}/{doc_id}.json.gz``, each a gzip of one
  ``NormalizedEvent`` dump) through a minimal async container protocol. The layout is mirrored
  here on purpose: the API never imports ``neurosphere_workers``.

The archive is partitioned by day, not by trace, so a lookup scans a bounded window of days and a
bounded number of blobs; hitting a bound sets ``truncated`` and the trace is labelled partial.
"""

from __future__ import annotations

import gzip
import json
import re
from collections.abc import AsyncIterator, Awaitable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final, Protocol, runtime_checkable

from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.paging import Page, PageRequest

from neurosphere_api.replay.models import TraceSummary

__all__ = [
    "ArchiveTraceReader",
    "BlobSource",
    "InMemoryTraceReader",
    "SpanRecord",
    "TraceReader",
    "TraceRecords",
    "record_from_archive",
    "summarize",
]

NO_DOMAIN: Final = "_none"
BLOB_SUFFIX: Final = ".json.gz"
_SAFE_SEGMENT: Final = re.compile(r"[^/\\\x00-\x1f]+")


@dataclass(frozen=True, slots=True)
class SpanRecord:
    """One stored span, flattened from the archive record. Timestamps are timezone-aware UTC."""

    customer_id: str
    domain_id: str | None
    trace_id: str
    span_id: str
    parent_span_id: str | None
    span_kind: str
    outcome: str
    event_time: datetime
    duration_ms: int | None
    ingestion_time: datetime | None = None
    late_flag: bool = False
    agent: str | None = None
    provider: str | None = None
    model: str | None = None
    sampling_rate: float | None = None
    sampling_method: str | None = None
    sampling_reason: str | None = None
    payload_pointer: str | None = None
    payload_redaction_state: str | None = None


@dataclass(frozen=True, slots=True)
class TraceRecords:
    spans: tuple[SpanRecord, ...]
    truncated: bool = False


@runtime_checkable
class TraceReader(Protocol):
    async def list_traces(
        self, customer_id: str, domain_id: str, page: PageRequest
    ) -> Page[TraceSummary]: ...

    async def get_trace(self, customer_id: str, domain_id: str, trace_id: str) -> TraceRecords: ...

    async def read_payload(
        self, customer_id: str, domain_id: str, pointer: str
    ) -> dict[str, Any] | None: ...


def summarize(records: list[SpanRecord]) -> TraceSummary:
    """Head row for one trace: earliest start, counts, lowest known sampling rate, root name."""
    ordered = sorted(records, key=lambda r: r.event_time)
    present = {r.span_id for r in records}
    roots = [r for r in ordered if r.parent_span_id is None or r.parent_span_id not in present]
    rates = [r.sampling_rate for r in records if r.sampling_rate is not None]
    root = roots[0] if roots else ordered[0]
    return TraceSummary(
        trace_id=ordered[0].trace_id,
        started_at=_iso(ordered[0].event_time),
        span_count=len(records),
        error_count=sum(1 for r in records if r.outcome in {"error", "timeout"}),
        sampling_rate=min(rates) if rates else None,
        root_name=root.agent or root.model or root.provider or root.span_kind,
    )


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _page_summaries(records: list[SpanRecord], page: PageRequest) -> Page[TraceSummary]:
    by_trace: dict[str, list[SpanRecord]] = {}
    for record in records:
        by_trace.setdefault(record.trace_id, []).append(record)
    heads = sorted(
        (summarize(group) for group in by_trace.values()),
        key=lambda h: (h.started_at, h.trace_id),
        reverse=True,
    )
    start = _decode_cursor(page.cursor)
    chunk = heads[start : start + page.page_size]
    more = start + page.page_size < len(heads)
    return Page[TraceSummary](
        items=tuple(chunk), next_cursor=f"o{start + page.page_size}" if more else None
    )


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    if cursor.startswith("o") and cursor[1:].isdigit():
        return int(cursor[1:])
    raise InvalidSchemaError("cursor is not valid", reason="cursor")


@dataclass
class InMemoryTraceReader:
    """Holds records for any customer/domain; every read filters by the supplied customer."""

    records: list[SpanRecord] = field(default_factory=list)
    payloads: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)

    def add(self, *records: SpanRecord) -> None:
        self.records.extend(records)

    async def list_traces(
        self, customer_id: str, domain_id: str, page: PageRequest
    ) -> Page[TraceSummary]:
        mine = [
            r for r in self.records if r.customer_id == customer_id and r.domain_id == domain_id
        ]
        return _page_summaries(mine, page)

    async def get_trace(self, customer_id: str, domain_id: str, trace_id: str) -> TraceRecords:
        found = [r for r in self.records if r.customer_id == customer_id and r.trace_id == trace_id]
        return TraceRecords(spans=tuple(found))

    async def read_payload(
        self, customer_id: str, domain_id: str, pointer: str
    ) -> dict[str, Any] | None:
        return self.payloads.get((customer_id, pointer))


@runtime_checkable
class BlobSource(Protocol):
    """The slice of ``azure.storage.blob.aio.ContainerClient`` the reader uses."""

    def list_blobs(
        self, name_starts_with: str | None = None, **kwargs: Any
    ) -> AsyncIterator[Any]: ...

    def download_blob(self, blob: str, **kwargs: Any) -> Awaitable[Any]: ...


def record_from_archive(doc: object) -> SpanRecord | None:
    """Flatten one archived ``NormalizedEvent`` dump; None for cost, untraced or malformed."""
    try:
        if not isinstance(doc, dict):
            return None
        message, contract = doc["message"], doc["contract"]
        trace_id, span_id = contract.get("trace_id"), contract.get("span_id")
        if message.get("kind") != "telemetry" or not trace_id or not span_id:
            return None
        sampling = contract.get("sampling") or {}
        payload = contract.get("payload_ref") or {}
        domain = contract.get("domain_id")
        return SpanRecord(
            customer_id=str(message["customer_id"]),
            domain_id=None if domain is None else str(domain),
            trace_id=str(trace_id),
            span_id=str(span_id),
            parent_span_id=_opt(contract.get("parent_span_id")),
            span_kind=str(contract.get("span_kind") or "unknown"),
            outcome=str(contract.get("outcome") or "unknown"),
            event_time=_parse(doc["event_time"]),
            duration_ms=contract.get("duration_ms"),
            ingestion_time=_parse(doc["ingestion_time"]) if doc.get("ingestion_time") else None,
            late_flag=bool(doc.get("late", False)),
            agent=_opt(contract.get("external_agent_id")),
            provider=_opt(contract.get("provider")),
            model=_opt(contract.get("model")),
            sampling_rate=sampling.get("rate"),
            sampling_method=_opt(sampling.get("method")),
            sampling_reason=_opt(sampling.get("reason")),
            payload_pointer=_opt(payload.get("pointer")),
            payload_redaction_state=_opt(payload.get("redaction_state")),
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def _opt(value: object) -> str | None:
    return None if value is None else str(value)


def _parse(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return parsed.astimezone(UTC)


def _segment(value: str) -> bool:
    return bool(_SAFE_SEGMENT.fullmatch(value)) and value not in {".", "..", NO_DOMAIN}


@dataclass
class ArchiveTraceReader:
    """Reads the redacted archive for ONE cloud/storage account (the container is injected)."""

    container: BlobSource
    lookback_days: int = 7
    max_blobs: int = 2_000
    today: Any = None  # Callable[[], date]; tests inject a fixed day

    def _days(self) -> list[date]:
        end = self.today() if self.today is not None else datetime.now(UTC).date()
        return [end - timedelta(days=n) for n in range(self.lookback_days)]

    async def _scan(self, customer_id: str, domain_id: str) -> TraceRecords:
        if not (_segment(customer_id) and _segment(domain_id)):
            return TraceRecords(spans=())
        out: list[SpanRecord] = []
        seen = 0
        truncated = False
        for day in self._days():
            prefix = f"{customer_id}/{domain_id}/{day:%Y/%m/%d}/"
            async for blob in self.container.list_blobs(name_starts_with=prefix):
                if not blob.name.startswith(prefix) or not blob.name.endswith(BLOB_SUFFIX):
                    continue
                if seen >= self.max_blobs:
                    truncated = True
                    break
                seen += 1
                try:
                    stream = await self.container.download_blob(blob.name)
                    doc = json.loads(gzip.decompress(await stream.readall()))
                except (OSError, ValueError, EOFError):
                    continue  # an unreadable blob is skipped, not fatal
                record = record_from_archive(doc)
                if record is not None and record.customer_id == customer_id:
                    out.append(record)
            if truncated:
                break
        return TraceRecords(spans=tuple(out), truncated=truncated)

    async def list_traces(
        self, customer_id: str, domain_id: str, page: PageRequest
    ) -> Page[TraceSummary]:
        scanned = await self._scan(customer_id, domain_id)
        return _page_summaries(list(scanned.spans), page)

    async def get_trace(self, customer_id: str, domain_id: str, trace_id: str) -> TraceRecords:
        scanned = await self._scan(customer_id, domain_id)
        return TraceRecords(
            spans=tuple(r for r in scanned.spans if r.trace_id == trace_id),
            truncated=scanned.truncated,
        )

    async def read_payload(
        self, customer_id: str, domain_id: str, pointer: str
    ) -> dict[str, Any] | None:
        # Payload bodies are not part of the PRP-07 archive layout; nothing to read here.
        return None
