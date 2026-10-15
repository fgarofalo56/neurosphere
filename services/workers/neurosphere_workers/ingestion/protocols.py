"""Hand-off interfaces to the sinks and state stores (implemented by PRP-07 items 3-6).

Contract for EVERY sink write: it MUST be idempotent by ``doc_id``. The pipeline may call a
write more than once for the same event (backoff retries, redelivery after a crash between a
sink write and the accepted marker); a repeat must overwrite with an equal document or be a
no-op, never add a second effect. First write wins is acceptable. Transient dependency
failures MUST be raised as ``DependencyTransientError`` (the pipeline retries only that);
any other exception is treated as a crash and propagates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from neurosphere_workers.ingestion.models import EventKey, NormalizedEvent, QuarantineRecord


@runtime_checkable
class QuarantineSink(Protocol):
    """Durable store for rejected messages. A failure here fails the batch (no checkpoint)."""

    async def write(self, record: QuarantineRecord) -> None:
        """Persist ``record``. Idempotent by ``record.doc_id``."""
        raise NotImplementedError


@runtime_checkable
class ArchiveSink(Protocol):
    """Redacted archive. Called once per newly accepted event."""

    async def write(self, event: NormalizedEvent) -> None:
        """Persist ``event``. Idempotent by ``event.doc_id``."""
        raise NotImplementedError


@runtime_checkable
class LedgerSink(Protocol):
    """Cost ledger and outbox. Called for EVERY accepted event; the ledger decides relevance."""

    async def accept(self, event: NormalizedEvent) -> None:
        """Apply ``event``. Idempotent by ``event.doc_id`` (no double counting on repeat)."""
        raise NotImplementedError


@runtime_checkable
class AcceptedMarkerStore(Protocol):
    """Records that every sink durably took an event. Written LAST (crash rule)."""

    async def is_accepted(self, key: EventKey) -> bool:
        """True when ``key`` was marked accepted."""
        raise NotImplementedError

    async def mark_accepted(self, key: EventKey) -> bool:
        """Mark ``key``. Idempotent: returns True if newly marked, False if already marked."""
        raise NotImplementedError


@runtime_checkable
class WatermarkStore(Protocol):
    """Per (customer, source) newest event time seen. Monotonic: it never moves backwards."""

    async def get(self, customer_id: str, source_id: str) -> datetime | None:
        """Newest event time recorded, or None when the source is new."""
        raise NotImplementedError

    async def advance(self, customer_id: str, source_id: str, event_time: datetime) -> datetime:
        """Record ``event_time`` if newer than the stored value; return the resulting maximum."""
        raise NotImplementedError
