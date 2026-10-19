"""Where the projection reads the subjects of ledger-change outbox entries from.

The WORKER may read the ledger (it is the API request path that must not). The outbox entry is a
pointer; the current ledger state is read, so a pointer to an older state of an entry still
projects the newest state, and the end state is the same whatever order entries are delivered in.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from neurosphere_core.ledger import AllocationRecord, LedgerEntry, LedgerStore


@runtime_checkable
class LedgerSource(Protocol):
    async def get_entry(self, customer_id: str, entry_id: str) -> LedgerEntry | None:
        raise NotImplementedError

    async def get_allocation(self, customer_id: str, allocation_id: str) -> AllocationRecord | None:
        raise NotImplementedError


class StoreLedgerSource:
    """``LedgerSource`` over a ``LedgerStore``. The store has no point read for allocations, so
    that lookup lists the customer's allocations (bounded by the billing volume, worker only)."""

    def __init__(self, store: LedgerStore) -> None:
        self._store = store

    async def get_entry(self, customer_id: str, entry_id: str) -> LedgerEntry | None:
        found = await self._store.read_entry(customer_id, entry_id)
        return None if found is None else found.entry

    async def get_allocation(self, customer_id: str, allocation_id: str) -> AllocationRecord | None:
        for record in await self._store.list_allocations(customer_id):
            if record.id == allocation_id:
                return record
        return None
