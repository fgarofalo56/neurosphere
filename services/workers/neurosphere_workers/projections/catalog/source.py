"""Where the catalog projection reads trace events back from (PRP-10 item 3).

An ``OutboxEntry`` is a POINTER (``ref_id`` is the event's ``doc_id``), so the handler needs the
event content. PRP-07 writes accepted events to the redacted blob archive, whose blob path needs
the event's domain and day, neither of which the outbox pointer carries, and it ships no reader.
That gap is isolated behind ``TraceEventSource`` so this package owns no storage convention; an
archive-backed implementation belongs to the PRP that adds the archive reader.

Implementations MUST be scoped to one customer (``customer_id`` is a parameter on every call), must
return only redacted telemetry (never a prompt or response body), and must raise
``DependencyTransientError`` for storage failures. ``None`` means "no such event".
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent

MAX_CHILD_SPANS: Final = 32
"""Upper bound on child spans one delegation lookup may return."""


@dataclass(frozen=True, slots=True)
class LoadedEvent:
    """A telemetry event plus the ``doc_id`` evidence pointers are built from."""

    doc_id: str
    event: TelemetryEvent


@runtime_checkable
class TraceEventSource(Protocol):
    async def get_event(self, customer_id: str, doc_id: str) -> LoadedEvent | None:
        """The accepted telemetry event stored under ``doc_id`` (None for cost or unknown)."""
        raise NotImplementedError

    async def find_span(self, customer_id: str, trace_id: str, span_id: str) -> LoadedEvent | None:
        """The event of one span of one trace, or None when it has not been stored."""
        raise NotImplementedError

    async def find_child_spans(
        self, customer_id: str, trace_id: str, parent_span_id: str
    ) -> Sequence[LoadedEvent]:
        """Events whose ``parent_span_id`` is given, at most ``MAX_CHILD_SPANS``."""
        raise NotImplementedError


class InMemoryTraceEventSource:
    """Dict-backed source for tests and the sandbox. Content is keyed by customer."""

    def __init__(self, events: Iterable[LoadedEvent] = ()) -> None:
        self._by_doc: dict[tuple[str, str], LoadedEvent] = {}
        self.reads = 0
        for loaded in events:
            self.add(loaded)

    def add(self, loaded: LoadedEvent) -> None:
        self._by_doc[(loaded.event.customer_id.root, loaded.doc_id)] = loaded

    async def get_event(self, customer_id: str, doc_id: str) -> LoadedEvent | None:
        self.reads += 1
        return self._by_doc.get((customer_id, doc_id))

    async def find_span(self, customer_id: str, trace_id: str, span_id: str) -> LoadedEvent | None:
        for (customer, _), loaded in self._by_doc.items():
            event = loaded.event
            if (
                customer == customer_id
                and event.trace_id is not None
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
            for (customer, _), loaded in self._by_doc.items()
            if customer == customer_id
            and loaded.event.trace_id is not None
            and loaded.event.trace_id.root == trace_id
            and loaded.event.parent_span_id is not None
            and loaded.event.parent_span_id.root == parent_span_id
        ]
        return sorted(found, key=lambda loaded: loaded.doc_id)[:MAX_CHILD_SPANS]
