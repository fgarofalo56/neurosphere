"""Cosmos-backed lifecycle job source and outcome sink (PRP-23 round 2 item 4).

``StoreJobSource`` adapts :class:`~neurosphere_core.lifecycle.jobs.JobStore.claim` to the
worker's ``JobSource``: pending jobs after a checkpoint, in submission order, each carrying the
audit context the API derived from the requesting principal. ``outcome_sink`` records every
engine outcome on its job (the same request id), so ``GET /api/v1/lifecycle/requests/{id}``
shows ``pending`` and then the outcome. Outcomes for requests that are not jobs (expiry sweeps)
are ignored by the store.
"""

from __future__ import annotations

from neurosphere_core.lifecycle import LifecycleOutcome
from neurosphere_core.lifecycle.jobs import JobStore, job_checkpoint

from neurosphere_workers.lifecycle.worker import OutcomeSink, RequestedJob

__all__ = ["StoreJobSource", "outcome_sink"]


class StoreJobSource:
    def __init__(self, store: JobStore) -> None:
        self._store = store

    async def next_jobs(self, checkpoint: str | None, limit: int) -> list[RequestedJob]:
        jobs = await self._store.claim(checkpoint, limit)
        return [
            RequestedJob(
                request=job.request,
                ctx=job.ctx,
                checkpoint=job_checkpoint(job),
                dry_run=job.dry_run,
            )
            for job in jobs
        ]


def outcome_sink(store: JobStore) -> OutcomeSink:
    async def record(outcome: LifecycleOutcome) -> None:
        await store.record_outcome(outcome.request_id, outcome)

    return record
