"""Worker base class and runner with graceful drain.

Lifecycle: fetch a batch from the last checkpoint, process it (with a bounded retry budget),
commit the checkpoint only after the batch was durably accepted or quarantined, repeat. A
shutdown request lets the in-flight batch finish and commit, then the loop exits and the
process returns 0. A crash mid-batch never reaches the commit, so the checkpoint keeps its
prior value and the batch is redelivered.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from neurosphere_workers.runtime.backoff import BackoffPolicy, Random, Sleep, retry_with_backoff
from neurosphere_workers.runtime.checkpoint import CheckpointStore
from neurosphere_workers.runtime.health import HealthServer, HealthStatus
from neurosphere_workers.runtime.signals import install_signal_handlers

logger = logging.getLogger("neurosphere.workers.runtime")


class BatchOutcome(StrEnum):
    """Only these two outcomes permit the checkpoint to advance."""

    ACCEPTED = "accepted"
    QUARANTINED = "quarantined"


class Batch(BaseModel):
    """A unit of work and the checkpoint value that is valid once it is durably handled."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[Any, ...]
    checkpoint: str


class Worker(ABC):
    """Subclass for each worker; one worker owns one partition key."""

    partition_key: str

    @abstractmethod
    async def fetch_batch(self, checkpoint: str | None) -> Batch | None:
        """Return the next batch after ``checkpoint``, or ``None`` when idle."""

    @abstractmethod
    async def process_batch(self, batch: Batch) -> BatchOutcome:
        """Durably accept or quarantine the batch. Raise DependencyTransientError to retry."""


class WorkerRunner:
    def __init__(
        self,
        worker: Worker,
        store: CheckpointStore,
        *,
        policy: BackoffPolicy | None = None,
        idle_seconds: float = 1.0,
        sleep: Sleep = asyncio.sleep,
        rng: Random = random.random,  # jitter only
        health: HealthServer | None = None,
    ) -> None:
        self._worker = worker
        self._store = store
        self._policy = policy or BackoffPolicy()
        self._idle_seconds = idle_seconds
        self._sleep = sleep
        self._rng = rng
        self._health = health
        self._shutdown = asyncio.Event()

    @property
    def status(self) -> HealthStatus:
        return "draining" if self._shutdown.is_set() else "ok"

    def request_shutdown(self) -> None:
        """Begin a graceful drain (what SIGTERM/SIGINT call; tests may call it directly)."""
        if not self._shutdown.is_set():
            logger.info("shutdown requested", extra={"event": "worker.draining"})
            self._shutdown.set()

    async def run(self, *, handle_signals: bool = True) -> int:
        """Run until shutdown; return the process exit code (0 on a clean drain)."""
        uninstall = install_signal_handlers(self.request_shutdown) if handle_signals else None
        if self._health is not None:
            await self._health.start()
        logger.info("worker started", extra={"event": "worker.started"})
        try:
            await self._loop()
        finally:
            if uninstall is not None:
                uninstall()
            if self._health is not None:
                await self._health.stop()
        logger.info("worker stopped", extra={"event": "worker.stopped"})
        return 0

    async def _loop(self) -> None:
        key = self._worker.partition_key
        while not self._shutdown.is_set():
            checkpoint = await self._store.get(key)
            batch = await self._worker.fetch_batch(checkpoint)
            if batch is None:
                await self._idle()
                continue
            outcome = await retry_with_backoff(
                lambda b=batch: self._worker.process_batch(b),
                self._policy,
                sleep=self._sleep,
                rng=self._rng,
            )
            # Advance only after durable accept or quarantine; a crash above skips this.
            await self._store.commit(key, batch.checkpoint)
            logger.info(
                "batch committed",
                extra={"event": "worker.batch_committed", "outcome": outcome.value},
            )

    async def _idle(self) -> None:
        with contextlib.suppress(TimeoutError):  # idle timeout elapsing is the normal case
            await asyncio.wait_for(self._shutdown.wait(), timeout=self._idle_seconds)


class IdleWorker(Worker):
    """Placeholder worker for the compose entrypoint: never has work."""

    partition_key = "idle"

    async def fetch_batch(self, checkpoint: str | None) -> Batch | None:
        return None

    async def process_batch(self, batch: Batch) -> BatchOutcome:  # pragma: no cover
        return BatchOutcome.ACCEPTED
