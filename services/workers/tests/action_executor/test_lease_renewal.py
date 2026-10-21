"""The lease outlives a long connector call: renewed while apply/rollback runs, never stolen.

A connector call whose apply is gated by an ``asyncio.Event`` stays "in flight" while the fake
clock moves past the original lease. Renewal ticks come from :class:`ManualSleep`, an injected
``sleep`` the test releases one tick at a time (no real sleeps).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from neurosphere_connector.write import ApplyResult, RollbackResult, WriteRequest
from neurosphere_core.actions import IntentKey
from neurosphere_workers.actions import (
    DEFAULT_LEASE,
    ActionExecutor,
    ActionExecutorWorker,
)

from .executor_support import CountingConnector, Harness, SimulatedCrash

TICK = timedelta(minutes=1)
SAFETY_TIMEOUT = 5.0  # seconds; only reached when a test is already failing


class ManualSleep:
    """Injected ``sleep``: each call parks until :meth:`tick` releases it."""

    def __init__(self) -> None:
        self.calls: list[float] = []
        self._waiter: asyncio.Future[None] | None = None
        self._armed = asyncio.Event()

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._waiter = waiter
        self._armed.set()
        try:
            await waiter
        finally:
            if self._waiter is waiter:  # cancelled while parked (the call returned)
                self._waiter = None
                self._armed.clear()

    async def tick(self, *, expect_rearm: bool = True) -> None:
        """Release the parked sleep; by default wait until the renewal ran and slept again."""
        await asyncio.wait_for(self._armed.wait(), SAFETY_TIMEOUT)
        self._armed.clear()
        waiter = self._waiter
        self._waiter = None
        assert waiter is not None
        waiter.set_result(None)
        if expect_rearm:
            await asyncio.wait_for(self._armed.wait(), SAFETY_TIMEOUT)
        else:
            for _ in range(50):  # let the (failing) renewal write run to completion
                await asyncio.sleep(0)


class GatedConnector(CountingConnector):
    """``apply``/``rollback`` block on an event until the test releases them."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = {"apply": asyncio.Event(), "rollback": asyncio.Event()}
        self.release = {"apply": asyncio.Event(), "rollback": asyncio.Event()}

    async def _gate(self, name: str) -> None:
        self.entered[name].set()
        await asyncio.wait_for(self.release[name].wait(), SAFETY_TIMEOUT)

    async def apply(self, request: WriteRequest) -> ApplyResult:
        await self._gate("apply")
        return await super().apply(request)

    async def rollback(self, applied: ApplyResult) -> RollbackResult:
        await self._gate("rollback")
        return await super().rollback(applied)


async def _start(h: Harness, sleep: ManualSleep, **options: Any) -> tuple[IntentKey, Any]:
    key = await h.executing()
    task = asyncio.create_task(h.executor("exec-1", sleep=sleep, **options).execute(key))
    return key, task


async def _tick_past(h: Harness, sleep: ManualSleep, span: timedelta) -> None:
    elapsed = timedelta(0)
    while elapsed <= span:
        h.clock.advance(TICK)
        elapsed += TICK
        await sleep.tick()


async def test_long_apply_keeps_its_lease_and_finalizes_with_its_after_audit() -> None:
    connector = GatedConnector()
    h = Harness(connector=connector)
    sleep = ManualSleep()
    key, task = await _start(h, sleep)
    await asyncio.wait_for(connector.entered["apply"].wait(), SAFETY_TIMEOUT)
    started = h.clock()
    await _tick_past(h, sleep, DEFAULT_LEASE)  # well past the lease taken at phase "applying"

    mid = (await h.current(key)).execution
    assert mid is not None
    assert mid.phase == "applying" and mid.lease_owner == "exec-1"
    assert mid.lease_expires_at is not None
    assert mid.lease_expires_at == h.clock() + DEFAULT_LEASE
    assert mid.lease_expires_at > started + DEFAULT_LEASE
    assert sleep.calls and all(s == TICK.total_seconds() for s in sleep.calls)

    other = await h.executor("exec-2").execute(key)
    assert (other.outcome, other.reason) == ("skipped", "execution_leased")
    worker = ActionExecutorWorker(h.executor("exec-2"), h.store, clock=h.clock)
    assert await worker.fetch_batch(None) is None

    connector.release["apply"].set()
    report = await asyncio.wait_for(task, SAFETY_TIMEOUT)
    assert (report.outcome, report.state) == ("succeeded", "succeeded")
    assert connector.count("apply") == 1
    assert ("after", "applied", None) in h.exec_events("after")
    done = (await h.current(key)).execution
    assert done is not None and done.verify_matched is True and done.attempts == 1


async def test_second_worker_defers_while_the_apply_window_is_open() -> None:
    """Defence in depth: a lapsed lease alone never turns an unobserved apply into a failure."""
    h = Harness()
    h.connector.crash_in_apply = "before_write"
    key = await h.executing()
    short: dict[str, Any] = {
        "lease": timedelta(minutes=4),
        "max_connector_call": timedelta(minutes=3),
    }
    with pytest.raises(SimulatedCrash):
        await h.executor("exec-1", **short).execute(key)
    h.connector.crash_in_apply = None
    h.clock.advance(timedelta(minutes=5))  # exec-1's lease lapsed; exec-2's window has not

    deferred = await h.executor("exec-2").execute(key)
    assert (deferred.outcome, deferred.reason) == ("deferred", "apply_window_open")
    mid = await h.current(key)
    assert mid.state == "executing" and mid.execution is not None
    assert mid.execution.phase == "applying" and mid.execution.lease_owner is None
    assert h.connector.count("apply") == 1

    h.clock.advance(DEFAULT_LEASE)
    final = await h.executor("exec-2").execute(key)
    assert (final.outcome, final.reason) == ("failed", "apply_not_observed")
    assert h.connector.count("apply") == 1


async def test_lost_renewal_means_the_first_worker_finalizes_nothing() -> None:
    connector = GatedConnector()
    h = Harness(connector=connector)
    sleep = ManualSleep()
    key, task = await _start(h, sleep)
    await asyncio.wait_for(connector.entered["apply"].wait(), SAFETY_TIMEOUT)
    await sleep.tick()  # one good renewal

    # Another worker takes the intent over (ETag moves under exec-1).
    current = await h.current(key)
    assert current.execution is not None
    taken = current.execution.model_copy(update={"lease_owner": "exec-2"})
    await h.service.record_execution(current, taken, now=h.clock())
    events_before = list(h.auditor.events)

    h.clock.advance(TICK)
    await sleep.tick(expect_rearm=False)  # renewal hits a stale ETag and stops
    connector.release["apply"].set()
    report = await asyncio.wait_for(task, SAFETY_TIMEOUT)

    assert (report.outcome, report.reason) == ("skipped", "lease_lost")
    assert connector.count("apply") == 1
    assert h.auditor.events == events_before  # no after-audit, no transition from exec-1
    after = await h.current(key)
    assert after.state == "executing" and after.execution is not None
    assert after.execution.lease_owner == "exec-2"
    assert after.execution.phase == "applying" and after.execution.apply_result is None


async def test_long_rollback_is_also_kept_leased() -> None:
    connector = GatedConnector()
    connector.release["apply"].set()
    connector.apply_noop = True  # verify fails -> rollback
    h = Harness(connector=connector)
    sleep = ManualSleep()
    key, task = await _start(h, sleep)
    await asyncio.wait_for(connector.entered["rollback"].wait(), SAFETY_TIMEOUT)
    await _tick_past(h, sleep, DEFAULT_LEASE)

    other = await h.executor("exec-2").execute(key)
    assert (other.outcome, other.reason) == ("skipped", "execution_leased")

    connector.release["rollback"].set()
    report = await asyncio.wait_for(task, SAFETY_TIMEOUT)
    assert (report.outcome, report.reason) == ("rolled_back", "verification_failed")
    assert connector.count("apply") == 1 and connector.count("rollback") == 1


@pytest.mark.parametrize(
    "options",
    [
        {"lease": timedelta(minutes=10)},  # shorter than the default max_connector_call
        {"lease": timedelta(minutes=5), "max_connector_call": timedelta(minutes=6)},
        {"lease": timedelta(minutes=20), "lease_renewal": timedelta(minutes=10)},
        {"max_connector_call": timedelta(0)},
        {"lease_renewal": timedelta(0)},
    ],
)
def test_lease_configuration_is_validated(options: dict[str, Any]) -> None:
    h = Harness()
    with pytest.raises(ValueError, match=r"lease|max_connector_call"):
        h.executor(**options)


def test_default_lease_outlives_the_default_connector_call() -> None:
    h = Harness()
    assert isinstance(h.executor(), ActionExecutor)
