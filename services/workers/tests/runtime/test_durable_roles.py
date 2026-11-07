"""PRP-05 G2: no role runs inert, and batch roles resume from a durable checkpoint."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

import pytest
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from neurosphere_connector.write import WriteTargetRegistry
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.errors import DependencyTransientError
from neurosphere_workers.runtime import (
    Batch,
    BatchOutcome,
    CheckpointStore,
    RoleConfigError,
    RoleSupervisor,
    Worker,
    WorkerRunner,
)
from neurosphere_workers.runtime.adapters import MultiWorkerRole, WorkerRole
from neurosphere_workers.runtime.backoff import BackoffPolicy
from neurosphere_workers.runtime.checkpoint import CosmosRuntimeCheckpointStore
from neurosphere_workers.runtime.factories import (
    RuntimeConfig,
    build_lifecycle,
    warn_if_actions_idle,
)

NO_SLEEP = BackoffPolicy(base_delay_seconds=0.01, max_delay_seconds=0.01, max_attempts=2)


class FakeContainer:
    """Minimal async Cosmos container double: (partition, id) -> document."""

    def __init__(self) -> None:
        self.docs: dict[tuple[str, str], dict[str, Any]] = {}

    async def read_item(self, item: str, partition_key: str) -> dict[str, Any]:
        try:
            return dict(self.docs[(partition_key, item)])
        except KeyError:
            raise CosmosResourceNotFoundError(message="not found") from None

    async def upsert_item(self, body: dict[str, Any]) -> dict[str, Any]:
        self.docs[(body["customer_id"], body["id"])] = dict(body)
        return body


class OneBatchWorker(Worker):
    """Serves ``[checkpoint+1]`` batches up to ``stop_at``; ``fail`` makes processing raise."""

    partition_key = "unit-worker"

    def __init__(self, runner_ref: list[WorkerRunner], *, stop_at: int, fail: bool = False) -> None:
        self._runner_ref = runner_ref
        self._stop_at = stop_at
        self._fail = fail
        self.fetched_from: list[str | None] = []

    async def fetch_batch(self, checkpoint: str | None) -> Batch | None:
        self.fetched_from.append(checkpoint)
        nxt = int(checkpoint or "0") + 1
        if nxt > self._stop_at:
            self._runner_ref[0].request_shutdown()
            return None
        return Batch(items=(nxt,), checkpoint=str(nxt))

    async def process_batch(self, batch: Batch) -> BatchOutcome:
        if self._fail:
            raise DependencyTransientError("down", reason="unit")
        return BatchOutcome.ACCEPTED


def _runner(store: CheckpointStore, worker: Worker, ref: list[WorkerRunner]) -> WorkerRunner:
    async def no_sleep(_seconds: float) -> None:
        return None

    runner = WorkerRunner(worker, store, policy=NO_SLEEP, idle_seconds=0.01, sleep=no_sleep)
    ref.append(runner)
    return runner


async def test_cosmos_runtime_store_satisfies_protocol_and_roundtrips() -> None:
    container = FakeContainer()
    store = CosmosRuntimeCheckpointStore(container, customer_id="cust-1")
    assert isinstance(store, CheckpointStore)
    assert await store.get("w") is None
    await store.commit("w", "5")
    await store.commit("w", "6")
    assert await store.get("w") == "6"
    # Another customer's partition never sees it.
    assert await CosmosRuntimeCheckpointStore(container, customer_id="cust-2").get("w") is None


async def test_restart_resumes_from_committed_checkpoint() -> None:
    container = FakeContainer()  # survives the "restart": it is the durable side
    ref: list[WorkerRunner] = []
    first = OneBatchWorker(ref, stop_at=3)
    await _runner(CosmosRuntimeCheckpointStore(container, customer_id="c"), first, ref).run(
        handle_signals=False
    )
    assert first.fetched_from[0] is None

    ref2: list[WorkerRunner] = []
    second = OneBatchWorker(ref2, stop_at=5)
    await _runner(CosmosRuntimeCheckpointStore(container, customer_id="c"), second, ref2).run(
        handle_signals=False
    )
    assert second.fetched_from[0] == "3"  # not None: a restart does not start over
    assert second.fetched_from[-1] == "5"


async def test_checkpoint_not_advanced_when_batch_fails() -> None:
    container = FakeContainer()
    store = CosmosRuntimeCheckpointStore(container, customer_id="c")
    await store.commit("unit-worker", "2")
    ref: list[WorkerRunner] = []
    worker = OneBatchWorker(ref, stop_at=9, fail=True)
    with pytest.raises(DependencyTransientError):
        await _runner(store, worker, ref).run(handle_signals=False)
    assert await store.get("unit-worker") == "2"


async def test_workerrole_uses_injected_durable_store() -> None:
    container = FakeContainer()
    store = CosmosRuntimeCheckpointStore(container, customer_id="c")
    ref: list[WorkerRunner] = []
    worker = OneBatchWorker(ref, stop_at=1)
    role = WorkerRole(worker, idle_seconds=0.01, checkpoints=store)
    ref.append(role._runner)
    await role.run()
    assert await store.get("unit-worker") == "1"


async def test_multiworkerrole_shares_the_store_by_partition_key() -> None:
    store = CosmosRuntimeCheckpointStore(FakeContainer(), customer_id="c")
    ref: list[WorkerRunner] = []
    role = MultiWorkerRole([OneBatchWorker(ref, stop_at=1)], idle_seconds=0.01, checkpoints=store)
    ref.append(role._roles[0]._runner)
    await role.run()
    assert await store.get("unit-worker") == "1"


async def test_lifecycle_role_refuses_to_run_inert(caplog: pytest.LogCaptureFixture) -> None:
    cfg = cast(RuntimeConfig, None)  # the refusal happens before any config or client is touched
    with caplog.at_level(logging.ERROR), pytest.raises(RoleConfigError) as raised:
        await build_lifecycle(cfg, ClientLifetime())
    assert raised.value.reason == "lifecycle_no_job_source"
    assert any(r.__dict__.get("event") == "worker.lifecycle_inert" for r in caplog.records)


async def test_supervisor_reports_inert_lifecycle_as_failed_with_reason() -> None:
    async def factory(lifetime: ClientLifetime) -> Any:
        return await build_lifecycle(cast(RuntimeConfig, None), lifetime)

    supervisor = RoleSupervisor({"lifecycle": factory}, policy=NO_SLEEP)
    task = asyncio.create_task(supervisor.run())
    for _ in range(100):
        if supervisor.snapshot()[0]["state"] == "failed":
            break
        await asyncio.sleep(0.01)
    snap = supervisor.snapshot()[0]
    supervisor.request_shutdown()
    await task
    assert snap["state"] == "failed"
    assert snap["reason"] == "lifecycle_no_job_source"
    assert snap["ready"] is False
    assert supervisor.ready is False


def test_actions_idle_warning_names_the_enabling_flags(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        assert warn_if_actions_idle(WriteTargetRegistry()) is True
    records = [
        r for r in caplog.records if r.__dict__.get("event") == "worker.actions_idle_by_config"
    ]
    assert len(records) == 1
    assert records[0].__dict__["enable_flags"] == ["NS_FOUNDRY_ENABLED", "NS_APIM_ENABLED"]
