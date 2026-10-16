"""In-memory implementations of every ingestion protocol, for tests of items 2-6.

Each fake counts calls (``write_calls``) separately from distinct effects (``effects``, keyed by
``doc_id``), so a test can assert "called twice, one effect". Failures are injectable:
``fail_transient(n)`` raises ``DependencyTransientError`` for the next n calls,
``crash_after_next_write()`` applies the write and then raises ``SimulatedCrash`` (the process
died after the sink took the data), ``fail_for(doc_id)`` makes one document fail forever.
"""

from __future__ import annotations

from datetime import datetime

from neurosphere_core.errors import DependencyTransientError

from neurosphere_workers.ingestion.models import EventKey, NormalizedEvent, QuarantineRecord


class SimulatedCrash(Exception):  # noqa: N818 - a test signal, not an error taxonomy member
    """Stands in for a process kill: not a DependencyTransientError, so it is never retried."""


class _Injectable:
    def __init__(self) -> None:
        self.write_calls = 0
        self._transient_left = 0
        self._crash_after_write = False
        self._fail_forever: set[str] = set()

    def fail_transient(self, times: int) -> None:
        self._transient_left = times

    def crash_after_next_write(self) -> None:
        self._crash_after_write = True

    def fail_for(self, doc_id: str) -> None:
        self._fail_forever.add(doc_id)

    def _before(self, doc_id: str) -> None:
        self.write_calls += 1
        if doc_id in self._fail_forever:
            raise DependencyTransientError("injected permanent failure", reason="injected")
        if self._transient_left > 0:
            self._transient_left -= 1
            raise DependencyTransientError("injected transient failure", reason="injected")

    def _after(self) -> None:
        if self._crash_after_write:
            self._crash_after_write = False
            raise SimulatedCrash


class FakeQuarantineSink(_Injectable):
    def __init__(self) -> None:
        super().__init__()
        self.effects: dict[str, QuarantineRecord] = {}

    async def write(self, record: QuarantineRecord) -> None:
        self._before(record.doc_id)
        self.effects.setdefault(record.doc_id, record)
        self._after()


class FakeArchiveSink(_Injectable):
    def __init__(self) -> None:
        super().__init__()
        self.effects: dict[str, NormalizedEvent] = {}

    async def write(self, event: NormalizedEvent) -> None:
        self._before(event.doc_id)
        self.effects.setdefault(event.doc_id, event)
        self._after()


class FakeLedgerSink(_Injectable):
    def __init__(self) -> None:
        super().__init__()
        self.effects: dict[str, NormalizedEvent] = {}

    async def accept(self, event: NormalizedEvent) -> None:
        self._before(event.doc_id)
        self.effects.setdefault(event.doc_id, event)
        self._after()


class FakeMarkerStore(_Injectable):
    def __init__(self) -> None:
        super().__init__()
        self.marked: set[EventKey] = set()

    async def is_accepted(self, key: EventKey) -> bool:
        return key in self.marked

    async def mark_accepted(self, key: EventKey) -> bool:
        self._before(key.doc_id)
        newly = key not in self.marked
        self.marked.add(key)
        self._after()
        return newly


class FakeWatermarkStore(_Injectable):
    def __init__(self) -> None:
        super().__init__()
        self.values: dict[tuple[str, str], datetime] = {}

    async def get(self, customer_id: str, source_id: str) -> datetime | None:
        return self.values.get((customer_id, source_id))

    async def advance(self, customer_id: str, source_id: str, event_time: datetime) -> datetime:
        self._before(f"{customer_id}|{source_id}")
        current = self.values.get((customer_id, source_id))
        if current is None or event_time > current:
            self.values[(customer_id, source_id)] = event_time
            current = event_time
        self._after()
        return current
