"""Event Hubs adapter for the normalizer.

Relation to the PRP-05 runtime. ``Worker``/``WorkerRunner`` is pull-based: the runner reads a
checkpoint from a ``CheckpointStore``, asks the worker to ``fetch_batch(checkpoint)`` and commits
after ``process_batch``. ``EventHubConsumerClient.receive_batch`` is push-based and owns partition
load balancing, ownership and its own blob checkpoint store, so squeezing it into
``fetch_batch`` would mean re-implementing ownership and partition fan-out for no gain. This
module therefore WRAPS rather than adapts: it keeps the runtime's rule (checkpoint only after a
durable accept or quarantine) by calling ``partition_context.update_checkpoint`` only after
``process_batch`` returned, and reuses the runtime's signal handling, backoff and
``BatchOutcome``. ``runtime/`` is not modified.

If ``process_batch`` raises, nothing is checkpointed. The exception propagates to the SDK, which
reports it through ``on_error`` and resumes the partition from its last checkpoint, so the batch
is redelivered (the pipeline tolerates redelivery by design).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from azure.eventhub import EventData
from azure.eventhub.aio import EventHubConsumerClient, PartitionContext
from neurosphere_core.errors import DependencyTransientError

from neurosphere_workers.ingestion.models import BatchResult, RawMessage
from neurosphere_workers.ingestion.pipeline import PipelineDeps, process_batch
from neurosphere_workers.ingestion.settings import IngestionSettings
from neurosphere_workers.runtime import install_signal_handlers

logger = logging.getLogger("neurosphere.workers.ingestion")

_CLOSE_TIMEOUT_SECONDS = 30.0


class PartitionContextLike(Protocol):
    """The slice of ``azure.eventhub.aio.PartitionContext`` this module uses."""

    partition_id: str

    async def update_checkpoint(self, event: Any = None) -> None:
        """Persist the position of ``event`` (the blob checkpoint store)."""
        raise NotImplementedError


class EventLike(Protocol):
    """The slice of ``azure.eventhub.EventData`` this module uses."""

    @property
    def body(self) -> Any: ...
    @property
    def offset(self) -> Any: ...
    @property
    def sequence_number(self) -> Any: ...
    @property
    def enqueued_time(self) -> datetime | None: ...


def to_raw_message(event: EventLike, partition_id: str) -> RawMessage:
    """Convert an SDK event; the body stays raw bytes (parsing is the pipeline's job)."""
    return RawMessage(
        body=b"".join(event.body),
        partition_id=partition_id,
        offset=str(event.offset),
        sequence_number=int(event.sequence_number),
        enqueued_time=event.enqueued_time or datetime.now(UTC),
    )


class IngestionConsumer:
    def __init__(
        self,
        client: EventHubConsumerClient,
        deps: PipelineDeps,
        settings: IngestionSettings,
    ) -> None:
        self._client = client
        self._deps = deps
        self._settings = settings
        self._shutdown = asyncio.Event()

    @property
    def draining(self) -> bool:
        return self._shutdown.is_set()

    def request_shutdown(self) -> None:
        if not self._shutdown.is_set():
            logger.info("shutdown requested", extra={"event": "ingestion.draining"})
            self._shutdown.set()

    async def on_event_batch(
        self, partition_context: PartitionContextLike, events: Sequence[EventLike]
    ) -> BatchResult | None:
        """Process one partition batch, then checkpoint. Raises (no checkpoint) on failure."""
        if not events:
            return None
        messages = [to_raw_message(e, partition_context.partition_id) for e in events]
        result = await process_batch(messages, self._deps, self._settings)
        # Only reached when process_batch returned: every message is accepted, a duplicate or
        # quarantined (PRP-07 C4).
        await partition_context.update_checkpoint(events[-1])
        logger.info(
            "batch checkpointed",
            extra={
                "event": "ingestion.batch_checkpointed",
                "outcome": result.outcome.value,
                "accepted": result.accepted,
                "duplicates": result.duplicates,
                "late": result.late,
                "quarantined": result.quarantined_total,
            },
        )
        return result

    async def run(self, *, handle_signals: bool = True) -> int:
        """Receive until shutdown; return the process exit code (0 on a clean stop)."""
        uninstall = install_signal_handlers(self.request_shutdown) if handle_signals else None

        async def _callback(partition_context: PartitionContext, events: list[EventData]) -> None:
            await self.on_event_batch(partition_context, events)

        receiver = asyncio.create_task(
            self._client.receive_batch(
                on_event_batch=_callback,
                max_batch_size=self._settings.max_batch_size,
                max_wait_time=self._settings.max_wait_seconds,
                starting_position="-1",
            )
        )
        stopper = asyncio.create_task(self._shutdown.wait())
        try:
            done, _ = await asyncio.wait({receiver, stopper}, return_when=asyncio.FIRST_COMPLETED)
            if receiver in done:
                receiver.result()  # surfaces a receiver crash
                return 1  # receive_batch only ends on its own when closed unexpectedly
            await self._client.close()  # lets receive_batch return after the in-flight batch
            # TimeoutError: ``receive_batch`` can sit in its load-balancing sleep (up to 30 s)
            # after close(); a slow drain is still a clean stop (the ``finally`` cancels it).
            with contextlib.suppress(
                asyncio.CancelledError, DependencyTransientError, TimeoutError
            ):
                await asyncio.wait_for(receiver, timeout=_CLOSE_TIMEOUT_SECONDS)
            return 0
        finally:
            stopper.cancel()
            if not receiver.done():
                receiver.cancel()
            if uninstall is not None:
                uninstall()
