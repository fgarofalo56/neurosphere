"""``CostLedger``: idempotent writer and ``StoreLedgerReader``: the read side."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.ledger.fold import fold_entry
from neurosphere_core.ledger.models import AllocationRecord, LedgerEntry, Observation, entry_id
from neurosphere_core.ledger.store import LedgerStore
from neurosphere_core.ledger.totals import (
    CurrencyTotal,
    LedgerFilters,
    TimeWindow,
    compute_totals,
)

MAX_WRITE_ATTEMPTS: Final = 5


@dataclass(frozen=True, slots=True)
class EntryChange:
    """``changed`` False means the stored entry already equalled the recomputed one (a repeat)."""

    entry: LedgerEntry
    changed: bool


class CostLedger:
    def __init__(self, store: LedgerStore, *, max_attempts: int = MAX_WRITE_ATTEMPTS) -> None:
        self._store = store
        self._max_attempts = max_attempts

    async def record(
        self, customer_id: str, request_id: str, cost_category: str, observation: Observation
    ) -> EntryChange:
        """Attach ``observation`` and recompute the entry from the FULL observation set.

        Idempotent: observations are keyed by ``doc_id``, so a repeat recomputes an equal entry
        and writes nothing. Raises ``DependencyTransientError`` after bounded ETag contention.
        """
        key = entry_id(customer_id, request_id, cost_category)
        for _ in range(self._max_attempts):
            current = await self._store.read_entry(customer_id, key)
            existing = [] if current is None else current.entry.observations
            entry = fold_entry(customer_id, request_id, cost_category, [*existing, observation])
            if current is not None and current.entry.content_hash == entry.content_hash:
                return EntryChange(current.entry, changed=False)
            if await self._store.write_entry(entry, None if current is None else current.version):
                return EntryChange(entry, changed=True)
        raise DependencyTransientError("ledger entry contention", reason="ledger_contention")

    async def record_allocation(self, record: AllocationRecord) -> AllocationRecord:
        stamped = record.with_hash()
        await self._store.put_allocation(stamped)
        return stamped


class StoreLedgerReader:
    def __init__(self, store: LedgerStore) -> None:
        self._store = store

    async def totals(
        self, customer_id: str, window: TimeWindow, filters: LedgerFilters | None = None
    ) -> dict[str, CurrencyTotal]:
        entries = await self._store.list_entries(customer_id, window)
        selected = [
            e
            for e in entries
            if e.customer_id == customer_id
            and window.contains(e.occurred_at)
            and (filters is None or filters.matches(e))
        ]
        return compute_totals(selected)

    async def get_entry(
        self, customer_id: str, request_id: str, cost_category: str
    ) -> LedgerEntry | None:
        found = await self._store.read_entry(
            customer_id, entry_id(customer_id, request_id, cost_category)
        )
        return None if found is None else found.entry
