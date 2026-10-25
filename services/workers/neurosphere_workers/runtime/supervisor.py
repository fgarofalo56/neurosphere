"""Role supervision: one task per configured role, restart with backoff, isolation between roles.

Each role is built by a factory (given its own ``ClientLifetime`` for the attempt) into a
:class:`RoleRunnable` and run until it stops. A crash (any exception, or an unexpected clean
return) marks the role ``backoff`` (readiness false), waits a jittered exponential delay and
builds the role again from scratch; it never touches another role. A ``RoleConfigError`` is
terminal for that role only (``failed``). A role that stayed up for ``stable_seconds`` resets its
failure streak. ``crash_looping`` is reported once the streak reaches ``crash_loop_threshold``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol

from neurosphere_core.clients import ClientLifetime

from neurosphere_workers.runtime.backoff import BackoffPolicy, Random, compute_delay
from neurosphere_workers.runtime.health import HealthStatus
from neurosphere_workers.runtime.roles import RoleConfigError

__all__ = ["RoleFactory", "RoleRunnable", "RoleState", "RoleSupervisor"]

logger = logging.getLogger("neurosphere.workers.supervisor")

RoleState = Literal["pending", "starting", "running", "backoff", "failed", "stopped"]
DEFAULT_CRASH_LOOP_THRESHOLD: Final = 3
DEFAULT_STABLE_SECONDS: Final = 30.0
DEFAULT_DRAIN_SECONDS: Final = 30.0
_UNEXPECTED_EXIT: Final = "exited_unexpectedly"


class RoleRunnable(Protocol):
    async def run(self) -> None:
        """Run until stopped; return normally only after ``request_shutdown``."""
        ...

    def request_shutdown(self) -> None: ...


RoleFactory = Callable[[ClientLifetime], Awaitable[RoleRunnable]]


@dataclass(slots=True)
class _Role:
    name: str
    state: RoleState = "pending"
    restarts: int = 0
    streak: int = 0
    reason: str | None = None
    runnable: RoleRunnable | None = None


class RoleSupervisor:
    def __init__(
        self,
        factories: Mapping[str, RoleFactory],
        *,
        policy: BackoffPolicy | None = None,
        crash_loop_threshold: int = DEFAULT_CRASH_LOOP_THRESHOLD,
        stable_seconds: float = DEFAULT_STABLE_SECONDS,
        drain_seconds: float = DEFAULT_DRAIN_SECONDS,
        rng: Random = random.random,  # jitter only
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._factories = dict(factories)
        self._roles = {name: _Role(name) for name in self._factories}
        self._policy = policy or BackoffPolicy(base_delay_seconds=1.0, max_delay_seconds=60.0)
        self._threshold = crash_loop_threshold
        self._stable = stable_seconds
        self._drain = drain_seconds
        self._rng = rng
        self._clock = clock
        self._stop = asyncio.Event()

    # -- state ------------------------------------------------------------------------------

    @property
    def status(self) -> HealthStatus:
        return "draining" if self._stop.is_set() else "ok"

    @property
    def ready(self) -> bool:
        """Every configured role is started (``running``); vacuously true when idle."""
        return all(r.state == "running" for r in self._roles.values())

    def snapshot(self) -> list[dict[str, Any]]:
        return [
            {
                "name": r.name,
                "state": r.state,
                "live": r.state != "failed",
                "ready": r.state == "running",
                "restarts": r.restarts,
                "crash_looping": r.streak >= self._threshold,
                "reason": r.reason,
            }
            for r in self._roles.values()
        ]

    def request_shutdown(self) -> None:
        if self._stop.is_set():
            return
        logger.info("shutdown requested", extra={"event": "worker.draining"})
        self._stop.set()
        for role in self._roles.values():
            if role.runnable is not None:
                role.runnable.request_shutdown()

    # -- run --------------------------------------------------------------------------------

    async def run(self) -> None:
        """Supervise every role until :meth:`request_shutdown`, then drain them."""
        tasks = [
            asyncio.create_task(self._supervise(role, self._factories[role.name]), name=role.name)
            for role in self._roles.values()
        ]
        await self._stop.wait()
        if tasks:
            _done, pending = await asyncio.wait(tasks, timeout=self._drain)
            for task in pending:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        for role in self._roles.values():
            if role.state != "failed":
                role.state = "stopped"

    async def _supervise(self, role: _Role, factory: RoleFactory) -> None:
        while not self._stop.is_set():
            role.state = "starting"
            started = self._clock()
            try:
                async with ClientLifetime() as lifetime:
                    role.runnable = await factory(lifetime)
                    if self._stop.is_set():
                        role.runnable.request_shutdown()
                    role.state = "running"
                    role.reason = None
                    await role.runnable.run()
                if self._stop.is_set():
                    return
                role.reason = _UNEXPECTED_EXIT
            except RoleConfigError as exc:
                role.state, role.reason, role.runnable = "failed", exc.reason, None
                logger.error(
                    "role cannot start: configuration",
                    extra={"event": "worker.role_config", "role": role.name, "reason": exc.reason},
                )
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                role.reason = type(exc).__name__
                logger.exception(
                    "role crashed", extra={"event": "worker.role_crashed", "role": role.name}
                )
            finally:
                role.runnable = None
            if self._clock() - started >= self._stable:
                role.streak = 0
            role.streak += 1
            role.restarts += 1
            role.state = "backoff"
            delay = compute_delay(self._policy, min(role.streak - 1, 16), self._rng)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
