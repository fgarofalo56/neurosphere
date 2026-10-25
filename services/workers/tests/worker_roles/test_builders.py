"""Role builders refuse (terminally) when their own configuration is missing; adapters; identity."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import Settings
from neurosphere_workers.runtime import RoleConfigError
from neurosphere_workers.runtime.adapters import IngestionRole, PeriodicTick, TickWorker, WorkerRole
from neurosphere_workers.runtime.factories import (
    RuntimeConfig,
    build_evaluation,
    build_recommendations,
)
from neurosphere_workers.runtime.identity import EnvClaimsSource, resolve_pseudonym_key
from neurosphere_workers.runtime.settings import AuthSettings, StoreSettings, WorkerSettings


def _config(**auth: str) -> RuntimeConfig:
    return RuntimeConfig(
        Settings(env="local"),
        WorkerSettings(),
        StoreSettings(),
        AuthSettings(**auth),  # type: ignore[arg-type]
    )


async def test_recommendations_needs_its_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NS_WORKER_REC_DATA_DIR", raising=False)
    async with ClientLifetime() as lifetime:
        with pytest.raises(RoleConfigError) as caught:
            await build_recommendations(_config(), lifetime)
    assert caught.value.reason == "recommendations_data_dir_missing"


async def test_recommendations_data_dir_must_exist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NS_WORKER_REC_DATA_DIR", str(tmp_path / "missing"))
    async with ClientLifetime() as lifetime:
        with pytest.raises(RoleConfigError) as caught:
            await build_recommendations(_config(), lifetime)
    assert caught.value.reason == "recommendations_data_dir_invalid"


async def test_evaluation_needs_its_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NS_WORKER_EVAL_DATA_DIR", raising=False)
    async with ClientLifetime() as lifetime:
        with pytest.raises(RoleConfigError) as caught:
            await build_evaluation(_config(), lifetime)
    assert caught.value.reason == "evaluation_data_dir_missing"


async def test_evaluation_refuses_unreadable_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NS_WORKER_EVAL_DATA_DIR", str(tmp_path))
    async with ClientLifetime() as lifetime:
        with pytest.raises(RoleConfigError) as caught:
            await build_evaluation(_config(), lifetime)
    assert caught.value.reason == "evaluation_data_invalid"


def test_customer_id_defaults_to_synthco_only_when_local() -> None:
    assert _config().customer_id == "synthco"
    assert _config(customer_id="acme").customer_id == "acme"
    nonlocal_cfg = RuntimeConfig(
        Settings(env="dev", cloud="commercial"),  # type: ignore[arg-type]
        WorkerSettings(),
        StoreSettings(),
        AuthSettings(),
    )
    with pytest.raises(RoleConfigError) as caught:
        _ = nonlocal_cfg.customer_id
    assert caught.value.reason == "customer_id_missing"


def test_pseudonym_key_local_default_and_non_local_refusal() -> None:
    local = resolve_pseudonym_key(AuthSettings(), env="local")
    assert resolve_pseudonym_key(AuthSettings(), env="local").reference == local.reference
    with pytest.raises(RoleConfigError) as caught:
        resolve_pseudonym_key(AuthSettings(), env="prod")
    assert caught.value.reason == "pseudonym_key_missing"
    with pytest.raises(RoleConfigError) as caught:
        resolve_pseudonym_key(AuthSettings(pseudonym_key="k" * 40), env="prod")  # type: ignore[arg-type]
    assert caught.value.reason == "pseudonym_key_reference_missing"


async def test_worker_claims_are_an_app_identity_for_the_deployment_cloud() -> None:
    tenant = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"
    claims = await EnvClaimsSource(
        Settings(env="local"), tenant_id=tenant, object_id="6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"
    ).claims()
    assert claims.identity_type == "app"
    assert claims.tenant_id == tenant
    assert claims.cloud.value == "commercial"


async def test_tick_worker_ticks_once_per_fetch_and_is_always_idle() -> None:
    ticks: list[int] = []

    async def tick() -> None:
        ticks.append(1)

    worker = TickWorker("t", tick)
    assert await worker.fetch_batch(None) is None
    assert await worker.fetch_batch(None) is None
    assert len(ticks) == 2


async def test_periodic_tick_respects_its_interval() -> None:
    calls: list[int] = []
    now = [0.0]

    async def job() -> None:
        calls.append(1)

    periodic = PeriodicTick(job, 10.0, clock=lambda: now[0])
    await periodic()
    await periodic()
    assert len(calls) == 1
    now[0] = 10.0
    await periodic()
    assert len(calls) == 2
    with pytest.raises(ValueError, match="positive"):
        PeriodicTick(job, 0)


async def test_worker_role_runs_ticks_until_shutdown() -> None:
    seen = asyncio.Event()

    async def tick() -> None:
        seen.set()

    role = WorkerRole(TickWorker("t", tick), idle_seconds=0.01)
    task = asyncio.create_task(role.run())
    await asyncio.wait_for(seen.wait(), 5)
    role.request_shutdown()
    await asyncio.wait_for(task, 5)


async def test_a_failing_tick_ends_the_role_run_so_the_supervisor_restarts_it() -> None:
    async def tick() -> None:
        raise RuntimeError("boom")

    role = WorkerRole(TickWorker("t", tick), idle_seconds=0.01)
    with pytest.raises(RuntimeError):
        await asyncio.wait_for(role.run(), 5)


async def test_ingestion_role_treats_an_unrequested_end_as_a_crash() -> None:
    class Consumer:
        draining = False

        async def run(self, *, handle_signals: bool = True) -> int:
            assert handle_signals is False  # the process owns signals, never a role
            return 1

        def request_shutdown(self) -> None:
            self.draining = True

    role = IngestionRole(Consumer())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        await role.run()
