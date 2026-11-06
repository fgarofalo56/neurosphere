"""The ``actions`` role runs the executor AND the review-reconcile sweep on shared services."""

from __future__ import annotations

import asyncio

import pytest
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.hitl import (
    DecisionLog,
    HitlService,
    InMemoryDecisionStore,
    InMemoryHitlStore,
    ReviewPolicyRegistry,
)
from neurosphere_workers.actions import ActionExecutorWorker, ReviewReconcileWorker
from neurosphere_workers.runtime.adapters import MultiWorkerRole, TickWorker
from neurosphere_workers.runtime.factories import RuntimeConfig, actions_role
from neurosphere_workers.runtime.roles import RoleConfigError
from neurosphere_workers.runtime.settings import AuthSettings, StoreSettings, WorkerSettings

from .executor_support import Harness
from .test_review_reconcile import AllowAll


def _config() -> RuntimeConfig:
    return RuntimeConfig(
        Settings(env="local"),
        WorkerSettings(),
        StoreSettings(),
        AuthSettings(customer_id="synthco"),  # type: ignore[arg-type]
    )


def _hitl() -> HitlService:
    audit = AuditRepository(InMemoryAuditStore())
    return HitlService(
        InMemoryHitlStore(),
        DecisionLog(audit, InMemoryDecisionStore()),
        audit,
        ReviewPolicyRegistry(),
        AllowAll(),
    )


def _role(h: Harness, hitl: HitlService) -> MultiWorkerRole:
    worker = ActionExecutorWorker(h.executor(), h.store)  # type: ignore[attr-defined]
    return actions_role(
        _config(), executor_worker=worker, hitl=hitl, actions=h.service, auditor=h.auditor
    )


def test_actions_role_registers_executor_and_sweep_on_shared_services() -> None:
    h = Harness()
    hitl = _hitl()
    role = _role(h, hitl)

    executor, sweep = role.workers
    assert isinstance(executor, ActionExecutorWorker)
    assert isinstance(sweep, ReviewReconcileWorker)
    assert sweep.partition_key == "action-review-reconcile"
    # Same HitlService / ActionService / auditor objects the executor wiring built.
    assert sweep._hitl is hitl  # pyright: ignore[reportPrivateUsage]
    assert sweep._actions is h.service  # pyright: ignore[reportPrivateUsage]
    assert sweep._auditor is h.auditor  # pyright: ignore[reportPrivateUsage]
    assert sweep._customer == "synthco"  # pyright: ignore[reportPrivateUsage]


def _role_with(cfg: RuntimeConfig) -> MultiWorkerRole:
    h = Harness()
    worker = ActionExecutorWorker(h.executor(), h.store)  # type: ignore[attr-defined]
    return actions_role(
        cfg, executor_worker=worker, hitl=_hitl(), actions=h.service, auditor=h.auditor
    )


def test_actions_role_refuses_unscoped_sweep_without_customer_id() -> None:
    cfg = RuntimeConfig(
        Settings(env="prod", cloud=CloudName.COMMERCIAL),
        WorkerSettings(),
        StoreSettings(),
        AuthSettings(customer_id=None),
    )
    with pytest.raises(RoleConfigError) as err:
        _role_with(cfg)
    assert err.value.reason == "customer_id_missing"


def test_actions_role_sweep_is_always_customer_scoped() -> None:
    local = RuntimeConfig(Settings(env="local"), WorkerSettings(), StoreSettings(), AuthSettings())
    configured = RuntimeConfig(
        Settings(env="prod", cloud=CloudName.COMMERCIAL),
        WorkerSettings(),
        StoreSettings(),
        AuthSettings(customer_id="acme"),  # type: ignore[arg-type]
    )
    for cfg, expected in ((local, local.customer_id), (configured, "acme")):
        sweep = _role_with(cfg).workers[1]
        assert isinstance(sweep, ReviewReconcileWorker)
        assert sweep._customer is not None  # pyright: ignore[reportPrivateUsage]
        assert sweep._customer == expected  # pyright: ignore[reportPrivateUsage]


async def test_multi_worker_role_runs_all_and_shuts_down_together() -> None:
    seen = {"a": asyncio.Event(), "b": asyncio.Event()}

    def worker(name: str) -> TickWorker:
        async def tick() -> None:
            seen[name].set()

        return TickWorker(name, tick)

    role = MultiWorkerRole([worker("a"), worker("b")], idle_seconds=0.01)
    task = asyncio.create_task(role.run())
    await asyncio.wait_for(asyncio.gather(seen["a"].wait(), seen["b"].wait()), 5)
    role.request_shutdown()
    await asyncio.wait_for(task, 5)


async def test_one_crashing_worker_ends_the_role_with_its_error() -> None:
    async def boom() -> None:
        raise RuntimeError("boom")

    async def idle() -> None:
        return None

    role = MultiWorkerRole([TickWorker("idle", idle), TickWorker("boom", boom)], idle_seconds=0.01)
    with pytest.raises(RuntimeError, match="boom"):
        await asyncio.wait_for(role.run(), 5)


def test_multi_worker_role_needs_a_worker() -> None:
    with pytest.raises(ValueError, match="at least one"):
        MultiWorkerRole([])
