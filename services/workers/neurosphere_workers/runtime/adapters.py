"""Adapters that make every role a supervised :class:`RoleRunnable`.

* :class:`WorkerRole`: a PRP-05 ``Worker`` under its own ``WorkerRunner`` (graceful drain,
  checkpoint rule, batch retry budget). Signals are owned by the process, never by a role.
* :class:`TickWorker`: a ``Worker`` whose "fetch" is one tick of a coroutine (outbox drains,
  periodic jobs); it always reports idle so the runner paces it with ``idle_seconds``.
* :class:`IngestionRole`: the Event Hubs consumer loop as a supervised task. A consumer that ends
  on its own is a crash (the supervisor rebuilds it).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from neurosphere_workers.ingestion.consumer import IngestionConsumer
from neurosphere_workers.runtime.checkpoint import InMemoryCheckpointStore
from neurosphere_workers.runtime.worker import Batch, BatchOutcome, Worker, WorkerRunner

__all__ = ["IngestionRole", "PeriodicTick", "TickWorker", "WorkerRole"]

logger = logging.getLogger("neurosphere.workers.runtime")

Tick = Callable[[], Awaitable[None]]


class TickWorker(Worker):
    """Runs ``tick`` once per runner iteration; never has a batch."""

    def __init__(self, partition_key: str, tick: Tick) -> None:
        self.partition_key = partition_key
        self._tick = tick

    async def fetch_batch(self, checkpoint: str | None) -> Batch | None:
        await self._tick()
        return None

    async def process_batch(self, batch: Batch) -> BatchOutcome:  # pragma: no cover
        return BatchOutcome.ACCEPTED


class PeriodicTick:
    """Calls ``job`` at most every ``interval_seconds`` (the first call is immediate)."""

    def __init__(
        self,
        job: Tick,
        interval_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._job = job
        self._interval = interval_seconds
        self._clock = clock
        self._last: float | None = None

    async def __call__(self) -> None:
        now = self._clock()
        if self._last is not None and now - self._last < self._interval:
            return
        # Stamp before the run: a failing job is retried by the supervisor, not in a hot loop.
        self._last = now
        await self._job()


class WorkerRole:
    def __init__(self, worker: Worker, *, idle_seconds: float = 1.0) -> None:
        self._runner = WorkerRunner(worker, InMemoryCheckpointStore(), idle_seconds=idle_seconds)

    async def run(self) -> None:
        await self._runner.run(handle_signals=False)

    def request_shutdown(self) -> None:
        self._runner.request_shutdown()


class IngestionRole:
    def __init__(self, consumer: IngestionConsumer) -> None:
        self._consumer = consumer

    async def run(self) -> None:
        await self._consumer.run(handle_signals=False)
        if not self._consumer.draining:
            raise RuntimeError("ingestion consumer ended without a shutdown request")

    def request_shutdown(self) -> None:
        self._consumer.request_shutdown()
