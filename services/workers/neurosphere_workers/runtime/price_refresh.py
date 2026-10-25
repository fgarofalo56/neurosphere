"""Periodic price table refresh for roles that price at runtime (aggregates).

Price sheets change while a worker runs (the stack seed writes one after the workers start), so a
table loaded once at build time goes stale. :class:`PriceTableRefresher` reloads the snapshot set
at most every ``interval_seconds`` and reports whether it changed; the caller swaps its pipeline
between ticks, never mid-entry. A failed reload keeps the previous table and is logged by
exception class name only (no values), and is retried after the next interval.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from neurosphere_core.ledger import PriceTable
from neurosphere_core.pricing.models import PriceSnapshot

__all__ = ["PriceTableRefresher", "SnapshotLoader"]

logger = logging.getLogger("neurosphere.workers.runtime")

SnapshotLoader = Callable[[], Awaitable[list[PriceSnapshot]]]

_Fingerprint = frozenset[tuple[str, str]]


def _fingerprint(snapshots: list[PriceSnapshot]) -> _Fingerprint:
    return frozenset((s.snapshot_id, s.content_hash) for s in snapshots)


def _table(snapshots: list[PriceSnapshot]) -> PriceTable:
    return PriceTable([s.to_price_version() for s in snapshots])


class PriceTableRefresher:
    """Holds the current :class:`PriceTable`; ``refresh_if_due`` reloads it on an interval."""

    def __init__(
        self,
        load: SnapshotLoader,
        initial: list[PriceSnapshot],
        interval_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._load = load
        self._interval = interval_seconds
        self._clock = clock
        self._last = clock()
        self._fingerprint = _fingerprint(initial)
        self._table = _table(initial)

    @property
    def table(self) -> PriceTable:
        return self._table

    async def refresh_if_due(self) -> bool:
        """Reload when the interval elapsed. True only when the snapshot set changed."""
        now = self._clock()
        if now - self._last < self._interval:
            return False
        # Stamp before the load: a failing store is retried next interval, not in a hot loop.
        self._last = now
        try:
            snapshots = await self._load()
            fingerprint = _fingerprint(snapshots)
            if fingerprint == self._fingerprint:
                return False
            table = _table(snapshots)
        except Exception as exc:
            logger.warning(
                "price refresh failed; keeping the previous table",
                extra={"event": "worker.price_refresh_failed", "error": type(exc).__name__},
            )
            return False
        self._fingerprint = fingerprint
        self._table = table
        logger.info(
            "price table refreshed",
            extra={"event": "worker.price_refreshed", "snapshots": len(snapshots)},
        )
        return True
