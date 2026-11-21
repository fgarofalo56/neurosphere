"""``StatusRecordingTick``: runs a connector tick, then stores its run status (PRP-139 item 3).

The wrapper adds one write per tick and nothing else:

* the wrapped tick runs first and its exception propagates unchanged (after a best-effort
  ``failed`` / ``tick_error`` write, so a crashing role does not look healthy);
* the observation (state, reason code, counts) is read from what the poller already keeps;
* the store is built lazily on the first write. Any failure to build it or to write is logged
  ONCE (event name and exception class only) and never fails the tick;
* ``once=True`` is for the idle branches: the status is written until one write succeeds, then
  the wrapper stays quiet, so an idling role does not write on every pass.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Final

from azure.cosmos.aio import CosmosClient
from neurosphere_core.sources_status import (
    ConnectorKind,
    ConnectorRunStatus,
    CosmosSourceStatusRepository,
    SourceStatusRepository,
)

from neurosphere_workers.connector_config import ConnectorIdle
from neurosphere_workers.sources_status.observe import RunObservation

__all__ = ["StatusRecordingTick", "cosmos_repository", "idle_recording"]

logger = logging.getLogger("neurosphere.workers.sources_status")

Tick = Callable[[], Awaitable[None]]
Observe = Callable[[], RunObservation]
RepositoryFactory = Callable[[], Awaitable[SourceStatusRepository]]
Clock = Callable[[], datetime]

TICK_ERROR: Final = "tick_error"


def _now() -> datetime:
    return datetime.now(UTC)


def cosmos_repository(
    cosmos: Callable[[], Awaitable[CosmosClient]], *, database: str
) -> RepositoryFactory:
    """A lazy factory for the Cosmos repository: nothing is opened until the first write."""

    async def build() -> SourceStatusRepository:
        return CosmosSourceStatusRepository.from_client(await cosmos(), database=database)

    return build


def idle_recording(
    kind: ConnectorKind,
    resolved: object,
    repository: RepositoryFactory,
    *,
    customer_id: str,
) -> StatusRecordingTick:
    """The idle branch's tick: does nothing, records once why (``idle`` or ``not_configured``).

    ``idle`` is a stored configuration that is disabled; everything else (no stored
    configuration, no settings) is ``not_configured``.
    """

    async def noop() -> None:
        return None

    disabled = isinstance(resolved, ConnectorIdle) and resolved.reason == "disabled"
    observation = (
        RunObservation("idle", "disabled") if disabled else RunObservation("not_configured", None)
    )
    return StatusRecordingTick(
        kind, noop, lambda: observation, repository, customer_id=customer_id, once=True
    )


class StatusRecordingTick:
    """Callable with the shape of a role tick (``async () -> None``)."""

    def __init__(
        self,
        kind: ConnectorKind,
        tick: Tick,
        observe: Observe,
        repository: RepositoryFactory,
        *,
        customer_id: str,
        before: Callable[[], object] | None = None,
        once: bool = False,
        clock: Clock = _now,
    ) -> None:
        self._kind: ConnectorKind = kind
        self._tick = tick
        self._observe = observe
        self._factory = repository
        self._customer = customer_id
        self._before = before
        self._once = once
        self._clock = clock
        self._repository: SourceStatusRepository | None = None
        self._warned = False
        self._done = False

    async def __call__(self) -> None:
        if self._once and self._done:
            return
        if self._before is not None:
            self._before()
        try:
            await self._tick()
        except Exception:
            await self._store(RunObservation("failed", TICK_ERROR))
            raise
        await self._store(self._observe())

    async def _store(self, observation: RunObservation) -> None:
        try:
            status = self._status(observation)
            if self._repository is None:
                self._repository = await self._factory()
            await self._repository.record(self._customer, status)
        except Exception as exc:  # a status write must never fail or stop a tick
            self._warn(exc)
            return
        self._done = True

    def _status(self, observation: RunObservation) -> ConnectorRunStatus:
        now = self._clock()
        succeeded = observation.state in ("ok", "partial")
        return ConnectorRunStatus(
            kind=self._kind,
            state=observation.state,
            reason=observation.reason,
            last_success_at=now if succeeded else None,
            last_attempt_at=now,
            counts=observation.counts,
        )

    def _warn(self, exc: Exception) -> None:
        if self._warned:
            return
        self._warned = True
        logger.warning(
            "connector run status not stored; the tick is unaffected",
            extra={
                "event": "worker.source_status_store_failed",
                "connector_kind": self._kind,
                "error": type(exc).__name__,
            },
        )
