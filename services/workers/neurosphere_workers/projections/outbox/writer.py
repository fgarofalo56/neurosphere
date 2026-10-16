"""Outbox writer: idempotent appends for accepted events and ledger changes."""

from __future__ import annotations

from neurosphere_core.ledger import AllocationRecord, LedgerEntry

from neurosphere_workers.projections.outbox.models import (
    OutboxEntry,
    event_outbox_id,
    ledger_change_outbox_id,
)
from neurosphere_workers.projections.outbox.stores import OutboxStore


class OutboxWriter:
    def __init__(self, store: OutboxStore) -> None:
        self._store = store

    async def write_event(self, entry: OutboxEntry) -> bool:
        """``entry.id`` must be the event ``doc_id``. True when newly written."""
        return await self._store.append(entry)

    async def write_ledger_change(self, state: LedgerEntry | AllocationRecord) -> bool:
        """One entry per distinct entry/allocation content: id = hash(entity id + content hash)."""
        is_entry = isinstance(state, LedgerEntry)
        request_id = state.request_id if isinstance(state, LedgerEntry) else None
        entry = OutboxEntry(
            id=ledger_change_outbox_id(state.id, state.content_hash),
            customer_id=state.customer_id,
            kind="ledger_change",
            ref_id=state.id,
            entity="ledger_entry" if is_entry else "allocation",
            content_hash=state.content_hash,
            source_id=None if is_entry else state.source_id,
            request_id=request_id,
        )
        return await self._store.append(entry)


__all__ = ["OutboxWriter", "event_outbox_id"]
