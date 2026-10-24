"""Lifecycle worker: requested jobs, queued (previously blocked) jobs and scheduled expiry sweeps.

Built on the PRP-05 ``Worker`` base. A job that fails read-back verification is ``failed`` and
audited by the engine; the batch is still durably handled (the failure is recorded), so the
checkpoint may advance. Store outages raise and the runner retries the batch.
Registration in the runtime entrypoint and deployment are follow-ups (not owned here).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from neurosphere_core.audit.builders import AuditContext
from neurosphere_core.lifecycle import (
    JobStatus,
    LifecycleEngine,
    LifecycleOutcome,
    LifecycleRequest,
)
from neurosphere_core.lifecycle.targets import LifecycleTarget

from neurosphere_workers.runtime.worker import Batch, BatchOutcome, Worker

Clock = Callable[[], datetime]
OutcomeSink = Callable[[LifecycleOutcome], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class RequestedJob:
    request: LifecycleRequest
    ctx: AuditContext
    checkpoint: str


class JobSource(Protocol):
    """Where requested jobs come from (a queue or a store); ordered by checkpoint."""

    async def next_jobs(self, checkpoint: str | None, limit: int) -> list[RequestedJob]: ...


@dataclass(frozen=True, slots=True)
class SweepSpec:
    target: LifecycleTarget
    data_class: str
    limit: int = 100


def _utc_now() -> datetime:
    return datetime.now(UTC)


class LifecycleWorker(Worker):
    partition_key = "lifecycle"

    def __init__(
        self,
        engine: LifecycleEngine,
        source: JobSource,
        *,
        sweeps: Sequence[SweepSpec] = (),
        sweep_ctx: AuditContext | None = None,
        sweep_interval: timedelta = timedelta(hours=1),
        queue_interval: timedelta = timedelta(minutes=1),
        batch_size: int = 50,
        clock: Clock = _utc_now,
        on_outcome: OutcomeSink | None = None,
    ) -> None:
        self._engine = engine
        self._source = source
        self._sweeps = tuple(sweeps)
        self._sweep_ctx = sweep_ctx
        self._interval = sweep_interval
        self._queue_interval = queue_interval
        self._last_queue_pass: datetime | None = None
        self._batch_size = batch_size
        self._clock = clock
        self._on_outcome = on_outcome
        self._last_sweep: datetime | None = None
        self.outcomes_failed = 0

    async def fetch_batch(self, checkpoint: str | None) -> Batch | None:
        jobs = await self._source.next_jobs(checkpoint, self._batch_size)
        if jobs:
            return Batch(items=tuple(jobs), checkpoint=jobs[-1].checkpoint)
        if self._queue_due() or self._sweep_due():
            return Batch(items=(), checkpoint=checkpoint or "0")
        return None

    def _queue_due(self) -> bool:
        last = self._last_queue_pass
        return last is None or self._clock() - last >= self._queue_interval

    def _sweep_due(self) -> bool:
        if not self._sweeps or self._sweep_ctx is None:
            return False
        return self._last_sweep is None or self._clock() - self._last_sweep >= self._interval

    async def _emit(self, outcome: LifecycleOutcome) -> None:
        if outcome.status is JobStatus.FAILED:
            self.outcomes_failed += 1
        if self._on_outcome is not None:
            await self._on_outcome(outcome)

    async def process_batch(self, batch: Batch) -> BatchOutcome:
        for job in batch.items:
            await self._emit(await self._engine.submit(job.request, job.ctx))
        for outcome in await self._engine.process_queue():
            await self._emit(outcome)
        self._last_queue_pass = self._clock()
        if self._sweep_due() and self._sweep_ctx is not None:
            for spec in self._sweeps:
                results = await self._engine.sweep_expiry(
                    self._sweep_ctx,
                    target=spec.target,
                    data_class=spec.data_class,
                    limit=spec.limit,
                )
                for outcome in results:
                    await self._emit(outcome)
            self._last_sweep = self._clock()
        return BatchOutcome.ACCEPTED
