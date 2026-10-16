"""Outbox reader with PER-SINK checkpoints (PRP-07 C5).

Each sink drains independently: its checkpoint advances only after its own handler succeeded for
an entry, a failing sink stops at the failing entry (order preserved) without touching any other
sink's progress, and a restart resumes from that sink's checkpoint. Delivery is at-least-once:
handlers must be idempotent by ``OutboxEntry.id``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Final

from neurosphere_workers.projections.outbox.models import OutboxEntry
from neurosphere_workers.projections.outbox.stores import CheckpointStore, OutboxStore

SINK_CATALOG: Final = "catalog"  # PRP-10 consumes
SINK_AGGREGATES: Final = "aggregates"  # PRP-14 consumes
KNOWN_SINKS: Final = (SINK_CATALOG, SINK_AGGREGATES)

SinkHandler = Callable[[OutboxEntry], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class SinkResult:
    sink: str
    delivered: int
    error: str | None = None  # exception class name only; never a message that could echo data

    @property
    def ok(self) -> bool:
        return self.error is None


class OutboxReader:
    def __init__(
        self, store: OutboxStore, checkpoints: CheckpointStore, *, batch_size: int = 100
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self._store = store
        self._checkpoints = checkpoints
        self._batch = batch_size

    async def drain(self, sink: str, customer_id: str, handler: SinkHandler) -> SinkResult:
        """Deliver everything after ``sink``'s checkpoint, in order, until empty or a failure."""
        delivered = 0
        cursor = await self._checkpoints.get(sink, customer_id)
        while True:
            batch = await self._store.read_after(customer_id, cursor, self._batch)
            if not batch:
                return SinkResult(sink, delivered)
            for stored in batch:
                try:
                    await handler(stored.entry)
                    await self._checkpoints.advance(sink, customer_id, stored.cursor)
                except Exception as exc:
                    return SinkResult(sink, delivered, type(exc).__name__)
                cursor = stored.cursor
                delivered += 1

    async def drain_all(
        self, customer_id: str, handlers: Mapping[str, SinkHandler]
    ) -> dict[str, SinkResult]:
        """Drain every sink independently; one sink's failure never affects another."""
        return {
            sink: await self.drain(sink, customer_id, handler) for sink, handler in handlers.items()
        }
