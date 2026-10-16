"""Ledger persistence protocol and the in-memory implementation.

Concurrency model: read-modify-write of an entry uses an opaque ``version`` token (Cosmos ETag).
``write_entry`` returns False on a precondition failure and the caller re-reads and retries (a
bounded number of times). There are no cross-item transactions: the Cosmos vNext emulator has
no stored procedures, and the design does not need them because every write is idempotent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from neurosphere_core.ledger.models import AllocationRecord, LedgerEntry
from neurosphere_core.ledger.totals import TimeWindow


@dataclass(frozen=True, slots=True)
class VersionedEntry:
    entry: LedgerEntry
    version: str


@runtime_checkable
class LedgerStore(Protocol):
    async def read_entry(self, customer_id: str, entry_id: str) -> VersionedEntry | None:
        raise NotImplementedError

    async def write_entry(self, entry: LedgerEntry, expected_version: str | None) -> bool:
        """Create (``expected_version`` None) or replace-if-unchanged. False = precondition
        failed (someone else wrote first): re-read and retry."""
        raise NotImplementedError

    async def list_entries(self, customer_id: str, window: TimeWindow) -> list[LedgerEntry]:
        """Entries of one customer with ``occurred_at`` in the half-open window."""
        raise NotImplementedError

    async def put_allocation(self, record: AllocationRecord) -> None:
        """Idempotent by ``record.id`` (deterministic from the observation doc_id)."""
        raise NotImplementedError

    async def list_allocations(self, customer_id: str) -> list[AllocationRecord]:
        raise NotImplementedError


class InMemoryLedgerStore:
    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], tuple[LedgerEntry, int]] = {}
        self._allocations: dict[tuple[str, str], AllocationRecord] = {}
        self.entry_writes = 0
        self.fail_next_writes = 0  # inject precondition failures

    async def read_entry(self, customer_id: str, entry_id: str) -> VersionedEntry | None:
        found = self._entries.get((customer_id, entry_id))
        return None if found is None else VersionedEntry(found[0], str(found[1]))

    async def write_entry(self, entry: LedgerEntry, expected_version: str | None) -> bool:
        if self.fail_next_writes > 0:
            self.fail_next_writes -= 1
            return False
        slot = (entry.customer_id, entry.id)
        current = self._entries.get(slot)
        if expected_version is None:
            if current is not None:
                return False
            self._entries[slot] = (entry, 1)
        else:
            if current is None or str(current[1]) != expected_version:
                return False
            self._entries[slot] = (entry, current[1] + 1)
        self.entry_writes += 1
        return True

    async def list_entries(self, customer_id: str, window: TimeWindow) -> list[LedgerEntry]:
        return [
            entry
            for (cust, _), (entry, _) in self._entries.items()
            if cust == customer_id and window.contains(entry.occurred_at)
        ]

    async def put_allocation(self, record: AllocationRecord) -> None:
        self._allocations.setdefault((record.customer_id, record.id), record)

    async def list_allocations(self, customer_id: str) -> list[AllocationRecord]:
        return [r for (cust, _), r in self._allocations.items() if cust == customer_id]
