"""``ActionExecutorWorker``: polls ``executing`` intents and runs them through the executor.

Built on the PRP-05 runtime base (:class:`~neurosphere_workers.runtime.Worker`), so it inherits
graceful drain, health and the runner loop. The work source is the intent store itself
(``IntentStore.list_in_states(("executing",))``), not an event stream: the "checkpoint" is only
the poll instant and carries no position, because the durable progress lives in each intent's
``ExecutionRecord`` and the ETag'd lease decides who runs it. Intents whose lease is live and
held by another worker are left out of the batch.

Per-intent failures never fail the batch: the executor reports them and leaves the intent in
``executing`` for a later poll. An unexpected exception is logged (intent id only) and the lease
lapses, so another pass or worker resumes through verify, never through a second apply.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final

from neurosphere_core.actions import IntentKey, IntentStore, StoredIntent

from neurosphere_workers.actions.executor import ActionExecutor, ExecutionReport, logger
from neurosphere_workers.runtime import Batch, BatchOutcome, Worker

__all__ = ["DEFAULT_BATCH_LIMIT", "ActionExecutorWorker"]

DEFAULT_BATCH_LIMIT: Final = 25

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ActionExecutorWorker(Worker):
    partition_key = "action-executor"

    def __init__(
        self,
        executor: ActionExecutor,
        store: IntentStore,
        *,
        batch_limit: int = DEFAULT_BATCH_LIMIT,
        clock: Clock = _utc_now,
    ) -> None:
        if not isinstance(executor, ActionExecutor):
            raise TypeError("executor must be an ActionExecutor (it carries the kill switch)")
        self._executor = executor
        self._store = store
        self._limit = batch_limit
        self._clock = clock
        self.reports: list[ExecutionReport] = []

    def _claimable(self, stored: StoredIntent, now: datetime) -> bool:
        record = stored.execution
        if record is None or record.lease_owner is None:
            return True
        if record.lease_owner == self._executor.worker_id:
            return True
        return record.lease_expires_at is None or record.lease_expires_at <= now

    async def fetch_batch(self, checkpoint: str | None) -> Batch | None:
        now = self._clock()
        rows = await self._store.list_in_states(("executing",), limit=self._limit)
        keys = tuple(s.key for s in rows if self._claimable(s, now))
        if not keys:
            return None
        return Batch(items=keys, checkpoint=now.isoformat())

    async def process_batch(self, batch: Batch) -> BatchOutcome:
        reports: list[ExecutionReport] = []
        for item in batch.items:
            if not isinstance(item, IntentKey):
                continue
            try:
                reports.append(await self._executor.execute(item))
            except Exception:
                logger.exception(
                    "executor pass crashed; the lease will lapse and the intent resumes",
                    extra={"event": "action.executor_error", "intent_id": item.intent_id},
                )
        self.reports = reports
        return BatchOutcome.ACCEPTED

    async def run_once(self) -> list[ExecutionReport]:
        """Fetch and process one batch (tests, CLIs); returns the pass reports."""
        batch = await self.fetch_batch(None)
        if batch is None:
            self.reports = []
            return []
        await self.process_batch(batch)
        return list(self.reports)
