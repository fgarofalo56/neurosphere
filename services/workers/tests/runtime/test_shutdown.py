import asyncio
import signal

import aiohttp
import pytest
from neurosphere_core.errors import DependencyTransientError
from neurosphere_workers.runtime import (
    BackoffPolicy,
    Batch,
    BatchOutcome,
    HealthServer,
    InMemoryCheckpointStore,
    Worker,
    WorkerRunner,
)


class SimulatedKill(BaseException):
    pass


class ScriptedWorker(Worker):
    partition_key = "p0"

    def __init__(self, batches: list[Batch]) -> None:
        self._batches = {b.checkpoint: b for b in batches}
        self._order = [b.checkpoint for b in batches]
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.block_first = False
        self.processed: list[str] = []
        self.kill_on: str | None = None

    async def fetch_batch(self, checkpoint: str | None) -> Batch | None:
        idx = 0 if checkpoint is None else self._order.index(checkpoint) + 1
        return self._batches[self._order[idx]] if idx < len(self._order) else None

    async def process_batch(self, batch: Batch) -> BatchOutcome:
        if batch.checkpoint == self.kill_on:
            raise SimulatedKill
        if self.block_first and not self.processed:
            self.started.set()
            await self.release.wait()
        self.processed.append(batch.checkpoint)
        return BatchOutcome.ACCEPTED


def _batches(*cps: str) -> list[Batch]:
    return [Batch(items=(c,), checkpoint=c) for c in cps]


async def test_drain_commits_after_in_flight_batch_and_exits_zero() -> None:
    store = InMemoryCheckpointStore()
    worker = ScriptedWorker(_batches("1", "2"))
    worker.block_first = True
    runner = WorkerRunner(worker, store, idle_seconds=0.01)
    task = asyncio.create_task(runner.run(handle_signals=False))
    await asyncio.wait_for(worker.started.wait(), 5)
    runner.request_shutdown()
    await asyncio.sleep(0.05)
    assert not task.done()  # still draining the in-flight batch
    assert await store.get("p0") is None  # not committed before completion
    worker.release.set()
    assert await asyncio.wait_for(task, 5) == 0
    assert await store.get("p0") == "1"  # in-flight committed, batch "2" never started
    assert worker.processed == ["1"]


async def test_sigkill_simulation_leaves_prior_checkpoint() -> None:
    store = InMemoryCheckpointStore()
    await store.commit("p0", "1")
    worker = ScriptedWorker(_batches("1", "2", "3"))
    worker.kill_on = "2"
    runner = WorkerRunner(worker, store, idle_seconds=0.01)
    with pytest.raises(SimulatedKill):
        await runner.run(handle_signals=False)
    assert await store.get("p0") == "1"


async def test_retry_exhaustion_does_not_advance_checkpoint() -> None:
    class Down(ScriptedWorker):
        async def process_batch(self, batch: Batch) -> BatchOutcome:
            raise DependencyTransientError("down")

    async def no_sleep(_s: float) -> None:
        return None

    store = InMemoryCheckpointStore()
    runner = WorkerRunner(
        Down(_batches("1")), store, policy=BackoffPolicy(max_attempts=2), sleep=no_sleep
    )
    with pytest.raises(DependencyTransientError):
        await runner.run(handle_signals=False)
    assert await store.get("p0") is None


async def test_health_reports_ok_then_draining() -> None:
    store = InMemoryCheckpointStore()
    worker = ScriptedWorker(_batches("1"))
    worker.block_first = True
    holder: list[WorkerRunner] = []
    health = HealthServer(lambda: holder[0].status, "127.0.0.1", 0)
    runner = WorkerRunner(worker, store, idle_seconds=0.01, health=health)
    holder.append(runner)
    task = asyncio.create_task(runner.run(handle_signals=False))
    await asyncio.wait_for(worker.started.wait(), 5)
    url = f"http://127.0.0.1:{health.bound_port}/healthz"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            assert resp.status == 200
            assert (await resp.json())["status"] == "ok"
        runner.request_shutdown()
        async with session.get(url) as resp:
            assert (await resp.json())["status"] == "draining"
    worker.release.set()
    assert await asyncio.wait_for(task, 5) == 0


async def test_real_signal_triggers_drain() -> None:
    store = InMemoryCheckpointStore()
    worker = ScriptedWorker(_batches("1"))
    runner = WorkerRunner(worker, store, idle_seconds=10)
    task = asyncio.create_task(runner.run())
    await asyncio.sleep(0.1)  # let handlers install and the loop go idle
    signal.raise_signal(signal.SIGTERM)
    assert await asyncio.wait_for(task, 5) == 0
    assert runner.status == "draining"
