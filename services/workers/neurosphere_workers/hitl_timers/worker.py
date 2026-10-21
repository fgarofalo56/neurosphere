"""Durable HITL timer worker (PRP-17 item 3, clarification 7).

Each tick: ``store.due(now)`` -> ``evaluate_timers`` -> ETag-conditional replace -> notify, via
``HitlService.apply_timers``. The worker holds no timer state at all: every deadline lives on the
stored review item, so a restarted (or second) worker computes the same actions from the store.

Concurrency: two workers that pick up the same due item race on the item's ETag. The loser gets
``stale_version`` and skips it; it never re-applies, so an SLA breach escalates exactly once.
A transient store failure mid-batch makes the runner retry the batch; items already applied in
the failed attempt now carry a new ETag and moved deadlines, so the retry skips them.

Runtime fit: this is a PRP-05 ``Worker``. ``fetch_batch`` returns the due items with the tick
instant as the checkpoint value. The checkpoint is informational only (last tick time); recovery
never depends on it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final

from neurosphere_core.hitl import HitlService, ReviewItem
from pydantic import BaseModel, ConfigDict

from neurosphere_workers.runtime import Batch, BatchOutcome, Worker

__all__ = ["DEFAULT_BATCH_LIMIT", "HitlTimerWorker", "TickReport"]

logger = logging.getLogger("neurosphere.workers.hitl_timers")

DEFAULT_BATCH_LIMIT: Final = 100

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _checkpoint(now: datetime) -> str:
    return now.astimezone(UTC).isoformat()


class TickReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    at: datetime
    due: int = 0
    applied: int = 0
    conflicts: int = 0
    escalated: int = 0
    expired: int = 0
    returned_to_pending: int = 0
    capped: int = 0
    notifications_failed: int = 0


class HitlTimerWorker(Worker):
    partition_key = "hitl-timers"

    def __init__(
        self,
        service: HitlService,
        *,
        clock: Clock = _utc_now,
        batch_limit: int = DEFAULT_BATCH_LIMIT,
    ) -> None:
        if batch_limit < 1:
            raise ValueError("batch_limit must be >= 1")
        self._service = service
        self._clock = clock
        self._limit = batch_limit
        self.last_report: TickReport | None = None

    @property
    def service(self) -> HitlService:
        return self._service

    async def fetch_batch(self, checkpoint: str | None) -> Batch | None:
        now = self._clock()
        due = await self._service.store.due(now, self._limit)
        if not due:
            return None
        return Batch(items=tuple(due), checkpoint=_checkpoint(now))

    async def process_batch(self, batch: Batch) -> BatchOutcome:
        now = datetime.fromisoformat(batch.checkpoint)
        self.last_report = await self._apply(
            [i for i in batch.items if isinstance(i, ReviewItem)], now
        )
        return BatchOutcome.ACCEPTED

    async def tick(self) -> TickReport:
        """One fetch-and-apply pass at ``clock()`` (what the runner loop does, without it)."""
        now = self._clock()
        batch = await self.fetch_batch(None)
        if batch is None:
            report = TickReport(at=now)
        else:
            await self.process_batch(batch)
            report = self.last_report or TickReport(at=now)
        self.last_report = report
        return report

    async def _apply(self, items: list[ReviewItem], now: datetime) -> TickReport:
        counts = {
            "applied": 0,
            "conflicts": 0,
            "escalated": 0,
            "expired": 0,
            "returned_to_pending": 0,
            "capped": 0,
            "notifications_failed": 0,
        }
        correlation_id = f"hitl-timers.{now.astimezone(UTC):%Y%m%dT%H%M%S%f}"
        for item in items:
            outcome = await self._service.apply_timers(item, now, correlation_id=correlation_id)
            if outcome.conflict:
                counts["conflicts"] += 1
                logger.info(
                    "timer skipped: item changed concurrently",
                    extra={"event": "hitl.timer_conflict"},
                )
                continue
            counts["notifications_failed"] += outcome.notifications_failed
            for action in outcome.applied:
                counts["applied"] += 1
                key = {
                    "escalate": "escalated",
                    "expire": "expired",
                    "return_to_pending": "returned_to_pending",
                    "cap_escalation": "capped",
                }[action.kind]
                counts[key] += 1
        return TickReport(at=now, due=len(items), **counts)
