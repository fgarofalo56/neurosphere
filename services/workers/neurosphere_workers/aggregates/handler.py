"""Aggregates sink handler for ``OutboxReader.drain(SINK_AGGREGATES, ...)`` (PRP-14 item 1).

Per outbox entry: resolve the subject to a ``Contribution``, REPLACE the subject's previous
contribution (or drop it when it fell out of the 90-day window), then rebuild every affected
bucket from the full set of that bucket's contributions. Because buckets are recomputed rather
than incremented, the handler is idempotent under at-least-once delivery and under a crash at any
point (the next delivery redoes the same deterministic steps), and a ledger entry whose content
changed (a new observation, a different day) moves cleanly between buckets.

The worker has no dependency on the analytics adapter: the hot aggregates keep updating and stay
readable while it is down. The handler RAISES on any failure (missing subject, store error) so the
reader never advances the checkpoint past an entry that is not durable.

Cost: a rebuild reads one day of one domain's contributions. That is bounded and worker-only;
sizing it against a real account is open (gate G07/G12), not claimed here.
Single writer per customer is assumed (the sink checkpoint is per customer); the status document
is a monotonic read-modify-write.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Final

from neurosphere_core.aggregates import (
    HOUR_RETENTION_DAYS,
    WINDOW_DAYS,
    AggregateStatus,
    AggregateStore,
    Contribution,
    Grain,
    bucket_start,
    format_bucket,
)
from neurosphere_core.errors import DependencyTransientError, ForbiddenError
from neurosphere_core.ledger import PriceTable

from neurosphere_workers.aggregates.mapping import (
    contribution_from_allocation,
    contribution_from_entry,
    contribution_from_event,
)
from neurosphere_workers.aggregates.rollups import rollup_bucket
from neurosphere_workers.aggregates.sources import LedgerSource
from neurosphere_workers.projections.catalog.source import TraceEventSource
from neurosphere_workers.projections.outbox import OutboxEntry

__all__ = ["AggregateProjection", "ProjectionStats", "hour_floor", "window_start"]

_ONE_HOUR: Final = timedelta(hours=1)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def window_start(now: datetime) -> datetime:
    """First instant of the rolling window: ``WINDOW_DAYS`` whole UTC days ending today."""
    return bucket_start(now, "day") - timedelta(days=WINDOW_DAYS - 1)


def hour_floor(now: datetime) -> datetime:
    """First hour bucket that is materialized: ``HOUR_RETENTION_DAYS`` whole UTC days."""
    return bucket_start(now, "day") - timedelta(days=HOUR_RETENTION_DAYS - 1)


@dataclass(slots=True)
class ProjectionStats:
    """Counters for observability and tests; never contain event content."""

    entries: int = 0
    ignored: int = 0
    applied: int = 0
    dropped_out_of_window: int = 0
    buckets_rebuilt: int = 0


class AggregateProjection:
    """Idempotent aggregates projection. ``handle`` is the ``SinkHandler`` for the sink."""

    def __init__(
        self,
        *,
        store: AggregateStore,
        ledger: LedgerSource,
        events: TraceEventSource,
        prices: PriceTable | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._store = store
        self._ledger = ledger
        self._events = events
        self._clock = clock
        self._price_dates: dict[str, date] = (
            {v.price_version_id: v.effective_date for v in prices.versions} if prices else {}
        )
        self.stats = ProjectionStats()

    async def __call__(self, entry: OutboxEntry) -> None:
        await self.handle(entry)

    async def handle(self, entry: OutboxEntry) -> None:
        self.stats.entries += 1
        contribution = await self._resolve(entry)
        if contribution is None:
            self.stats.ignored += 1
            return
        if contribution.customer_id != entry.customer_id:
            raise ForbiddenError("subject belongs to another customer than the outbox entry")
        await self._apply(contribution)

    async def prune(self, customer_id: str) -> int:
        """Delete data that left the window (contributions and day docs older than the window,
        hour docs older than the hour retention). Safe to run any time; idempotent."""
        now = self._clock()
        return await self._store.prune(
            customer_id, day_cutoff=window_start(now).date(), hour_cutoff=hour_floor(now)
        )

    # ------------------------------------------------------------------ subject resolution

    async def _resolve(self, entry: OutboxEntry) -> Contribution | None:
        if entry.kind == "event":
            if entry.event_kind == "cost":
                return None  # cost events reach the aggregates through their ledger entry
            loaded = await self._events.get_event(entry.customer_id, entry.ref_id)
            if loaded is None:
                raise DependencyTransientError(
                    "trace event is not readable yet", reason="trace_event_missing"
                )
            return contribution_from_event(entry.customer_id, loaded.doc_id, loaded.event)
        if entry.entity == "ledger_entry":
            ledger_entry = await self._ledger.get_entry(entry.customer_id, entry.ref_id)
            if ledger_entry is None:
                raise DependencyTransientError(
                    "ledger entry is not readable yet", reason="ledger_entry_missing"
                )
            return contribution_from_entry(ledger_entry)
        if entry.entity == "allocation":
            record = await self._ledger.get_allocation(entry.customer_id, entry.ref_id)
            if record is None:
                raise DependencyTransientError(
                    "allocation is not readable yet", reason="allocation_missing"
                )
            return contribution_from_allocation(record)
        return None

    # ------------------------------------------------------------------ durable write

    async def _apply(self, contribution: Contribution) -> None:
        now = self._clock()
        customer = contribution.customer_id
        previous = await self._store.get_contribution(customer, contribution.id)
        in_window = contribution.occurred >= window_start(now)
        affected: list[Contribution] = [] if previous is None else [previous]
        if in_window:
            await self._store.put_contribution(contribution)
            affected.append(contribution)
            self.stats.applied += 1
        else:
            if previous is not None:
                await self._store.delete_contribution(customer, contribution.id)
            self.stats.dropped_out_of_window += 1
        await self._rebuild(customer, affected, now)
        await self._advance_status(contribution)

    async def _rebuild(self, customer_id: str, affected: list[Contribution], now: datetime) -> None:
        hours_by_day: dict[tuple[str, date], set[datetime]] = {}
        for item in affected:
            moment = item.occurred
            hours_by_day.setdefault((item.domain_id, moment.date()), set()).add(
                bucket_start(moment, "hour")
            )
        for (domain, day), hours in sorted(hours_by_day.items()):
            day_start = datetime(day.year, day.month, day.day, tzinfo=UTC)
            members = await self._store.list_contributions(customer_id, domain, day)
            if day_start >= window_start(now):
                await self._write(customer_id, domain, "day", day_start, members)
            for hour in sorted(hours):
                if hour < hour_floor(now):
                    continue
                inside = [c for c in members if hour <= c.occurred < hour + _ONE_HOUR]
                await self._write(customer_id, domain, "hour", hour, inside)

    async def _write(
        self,
        customer_id: str,
        domain: str,
        grain: Grain,
        start: datetime,
        members: list[Contribution],
    ) -> None:
        docs = rollup_bucket(customer_id, domain, grain, start, members, self._price_dates)
        await self._store.replace_bucket(customer_id, domain, grain, format_bucket(start), docs)
        self.stats.buckets_rebuilt += 1

    async def _advance_status(self, contribution: Contribution) -> None:
        current = await self._store.status(contribution.customer_id)
        base = current or AggregateStatus(customer_id=contribution.customer_id)
        updated = base.model_copy(
            update={
                "watermark": _later(base.watermark, contribution.observed_at),
                "billing_observed_at": _later(
                    base.billing_observed_at, contribution.billing_observed_at
                ),
            }
        )
        if current is None or updated != current:
            await self._store.put_status(updated)


def _later(current: str | None, candidate: str | None) -> str | None:
    if candidate is None:
        return current
    return candidate if current is None or candidate > current else current
