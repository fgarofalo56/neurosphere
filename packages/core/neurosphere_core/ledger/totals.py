"""Totals over ledger entries: per ISO currency, never across currencies, never "complete" when
some entries are unknown (PRP-07 C12; null/unknown is never 0).

For each currency bucket: ``amount`` is the sum of the entries whose authoritative amount is
known (``None`` when none is), ``coverage`` is ``known / entries`` in [0, 1], ``unresolved_count``
counts entries with no amount because no price version resolved, ``unknown_count`` counts the
other entries with no amount (unknown tokens, currency conflict). Entries with no determinable
currency fall in the ``XXX`` bucket (ISO "no currency") so they stay visible, and because they
could belong to any currency they are also counted (as missing) in every real currency's
``entry_count``, ``coverage`` and unresolved/unknown counts.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from neurosphere_core.ledger.models import UNKNOWN_CURRENCY, LedgerEntry, Money, quantize


@dataclass(frozen=True, slots=True)
class TimeWindow:
    """Half-open ``[start, end)`` over ``LedgerEntry.occurred_at``."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("window bounds must be timezone-aware")
        if self.end < self.start:
            raise ValueError("window end precedes start")

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end


@dataclass(frozen=True, slots=True)
class LedgerFilters:
    cloud: str | None = None
    domain_id: str | None = None
    provider: str | None = None
    model: str | None = None
    source_id: str | None = None

    def matches(self, entry: LedgerEntry) -> bool:
        return (
            (self.cloud is None or entry.cloud == self.cloud)
            and (self.domain_id is None or entry.domain_id == self.domain_id)
            and (self.provider is None or entry.provider == self.provider)
            and (self.model is None or entry.model == self.model)
            and (self.source_id is None or entry.source_id == self.source_id)
        )


class CurrencyTotal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    amount: Money | None
    coverage: float
    entry_count: int
    known_count: int
    unresolved_count: int
    unknown_count: int

    @property
    def complete(self) -> bool:
        return self.entry_count > 0 and self.known_count == self.entry_count


def compute_totals(entries: Iterable[LedgerEntry]) -> dict[str, CurrencyTotal]:
    buckets: dict[str, list[LedgerEntry]] = {}
    for entry in entries:
        key = (
            entry.authoritative_currency
            if entry.authoritative_amount is not None and entry.authoritative_currency
            else _entry_currency(entry)
        )
        buckets.setdefault(key, []).append(entry)
    # Entries with no determinable currency could belong to any real currency, so they count
    # against every real currency's coverage (a total is never presented as complete while they
    # exist). They also keep their own XXX bucket.
    unattributed = buckets.get(UNKNOWN_CURRENCY, [])
    result: dict[str, CurrencyTotal] = {}
    for currency in sorted(buckets):
        group = list(buckets[currency])
        if currency != UNKNOWN_CURRENCY:
            group += unattributed
        known = [e for e in buckets[currency] if e.authoritative_amount is not None]
        missing = [e for e in group if e.authoritative_amount is None]
        total = (
            quantize(
                sum((e.authoritative_amount for e in known if e.authoritative_amount), Decimal(0))
            )
            if known
            else None
        )
        unresolved = sum(1 for e in missing if e.price_unresolved)
        result[currency] = CurrencyTotal(
            amount=total,
            coverage=len(known) / len(group),
            entry_count=len(group),
            known_count=len(known),
            unresolved_count=unresolved,
            unknown_count=len(missing) - unresolved,
        )
    return result


def _entry_currency(entry: LedgerEntry) -> str:
    """Currency bucket of an entry with no authoritative amount: the one its sources agree on."""
    currencies = {g.currency for g in entry.sources if g.currency is not None}
    return next(iter(currencies)) if len(currencies) == 1 else UNKNOWN_CURRENCY


@runtime_checkable
class LedgerReader(Protocol):
    """Read side for later aggregates (PRP-14)."""

    async def totals(
        self, customer_id: str, window: TimeWindow, filters: LedgerFilters | None = None
    ) -> dict[str, CurrencyTotal]:
        """Per-currency totals with coverage. Scoped to ``customer_id`` only."""
        raise NotImplementedError

    async def get_entry(
        self, customer_id: str, request_id: str, cost_category: str
    ) -> LedgerEntry | None:
        raise NotImplementedError
