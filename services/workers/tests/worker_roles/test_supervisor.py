"""Supervision: isolation between roles, restart with backoff, readiness, config failures."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import aiohttp
from neurosphere_core.clients import ClientLifetime
from neurosphere_workers.runtime import BackoffPolicy, HealthServer, RoleConfigError, RoleSupervisor
from neurosphere_workers.runtime.supervisor import RoleFactory, RoleRunnable

FAST = BackoffPolicy(base_delay_seconds=0.01, max_delay_seconds=0.01)


class FakeRole:
    """Runs until shutdown; ``crash`` makes the current run raise."""

    def __init__(self) -> None:
        self.running = asyncio.Event()
        self.stopped = asyncio.Event()
        self._crash = asyncio.Event()
        self._stop = asyncio.Event()

    def crash(self) -> None:
        self._crash.set()

    async def run(self) -> None:
        self.running.set()
        stop = asyncio.create_task(self._stop.wait())
        crash = asyncio.create_task(self._crash.wait())
        try:
            done, _ = await asyncio.wait({stop, crash}, return_when=asyncio.FIRST_COMPLETED)
            if crash in done and stop not in done:
                raise RuntimeError("boom")
        finally:
            stop.cancel()
            crash.cancel()
            self.stopped.set()

    def request_shutdown(self) -> None:
        self._stop.set()


class Roster:
    """Factory source that remembers every instance each role was built into."""

    def __init__(self, *names: str) -> None:
        self.built: dict[str, list[FakeRole]] = {n: [] for n in names}

    def factory(self, name: str) -> RoleFactory:
        async def build(_lifetime: ClientLifetime) -> RoleRunnable:
            role = FakeRole()
            self.built[name].append(role)
            return role

        return build

    def factories(self) -> dict[str, RoleFactory]:
        return {n: self.factory(n) for n in self.built}


def _supervisor(roster: Roster, **kwargs: Any) -> RoleSupervisor:
    return RoleSupervisor(roster.factories(), policy=FAST, rng=lambda: 0.0, **kwargs)


def _by_name(supervisor: RoleSupervisor) -> dict[str, dict[str, Any]]:
    return {r["name"]: r for r in supervisor.snapshot()}


async def until(predicate: Callable[[], bool], *, within: float = 5.0) -> None:
    """Bounded wait for ``predicate`` (one timeout; 5 ms steps, no tight loop)."""

    async def poll() -> None:
        for _ in range(int(within / 0.005) + 1):
            if predicate():
                return
            await asyncio.sleep(0.005)
        raise AssertionError("condition never became true")

    await asyncio.wait_for(poll(), within + 1)


async def _wait_state(supervisor: RoleSupervisor, name: str, state: str) -> None:
    await until(lambda: _by_name(supervisor)[name]["state"] == state)


async def test_killing_one_role_leaves_the_others_running() -> None:
    roster = Roster("ingestion", "aggregates", "projections")
    supervisor = _supervisor(roster)
    task = asyncio.create_task(supervisor.run())
    for name in roster.built:
        await _wait_state(supervisor, name, "running")
    assert supervisor.ready

    victim = roster.built["aggregates"][0]
    victim.crash()
    await asyncio.wait_for(victim.stopped.wait(), 5)

    # The crashed role is restarted into a fresh instance; the others are never rebuilt.
    await until(
        lambda: (
            len(roster.built["aggregates"]) >= 2 and roster.built["aggregates"][1].running.is_set()
        )
    )
    assert len(roster.built["ingestion"]) == 1
    assert len(roster.built["projections"]) == 1
    assert not roster.built["ingestion"][0].stopped.is_set()
    assert not roster.built["projections"][0].stopped.is_set()
    await _wait_state(supervisor, "aggregates", "running")
    assert _by_name(supervisor)["aggregates"]["restarts"] == 1

    supervisor.request_shutdown()
    await asyncio.wait_for(task, 5)
    assert supervisor.status == "draining"


async def test_readiness_reports_the_crashed_role_while_it_is_down() -> None:
    roster = Roster("ingestion", "actions")
    gate = asyncio.Event()
    inner = roster.factory("actions")
    attempts = 0

    async def gated(lifetime: ClientLifetime) -> RoleRunnable:
        nonlocal attempts
        attempts += 1
        if attempts > 1:
            await gate.wait()  # hold the restart so the "down" window is observable
        return await inner(lifetime)

    factories = {"ingestion": roster.factory("ingestion"), "actions": gated}
    supervisor = RoleSupervisor(factories, policy=FAST, rng=lambda: 0.0)
    task = asyncio.create_task(supervisor.run())
    await _wait_state(supervisor, "actions", "running")
    await _wait_state(supervisor, "ingestion", "running")

    roster.built["actions"][0].crash()
    await _wait_state(supervisor, "actions", "starting")
    assert not supervisor.ready
    snapshot = _by_name(supervisor)
    assert snapshot["actions"]["ready"] is False
    assert snapshot["actions"]["reason"] == "RuntimeError"
    assert snapshot["ingestion"]["ready"] is True

    gate.set()
    await _wait_state(supervisor, "actions", "running")
    assert supervisor.ready
    supervisor.request_shutdown()
    await asyncio.wait_for(task, 5)


async def test_a_role_that_keeps_crashing_is_reported_crash_looping_and_never_ready() -> None:
    names = ("lifecycle", "evaluation")
    roster = Roster(*names)
    inner = roster.factory("lifecycle")

    async def crash_on_start(lifetime: ClientLifetime) -> RoleRunnable:
        role = await inner(lifetime)
        assert isinstance(role, FakeRole)
        role.crash()
        return role

    factories = {"lifecycle": crash_on_start, "evaluation": roster.factory("evaluation")}
    supervisor = RoleSupervisor(
        factories, policy=FAST, rng=lambda: 0.0, crash_loop_threshold=3, stable_seconds=60
    )
    task = asyncio.create_task(supervisor.run())

    await until(lambda: _by_name(supervisor)["lifecycle"]["crash_looping"])
    assert _by_name(supervisor)["evaluation"]["crash_looping"] is False
    assert not supervisor.ready
    supervisor.request_shutdown()
    await asyncio.wait_for(task, 5)


async def test_config_error_is_terminal_for_that_role_only() -> None:
    roster = Roster("projections")

    async def misconfigured(_lifetime: ClientLifetime) -> RoleRunnable:
        raise RoleConfigError("worker_object_id_missing")

    factories = {"recommendations": misconfigured, "projections": roster.factory("projections")}
    supervisor = RoleSupervisor(factories, policy=FAST, rng=lambda: 0.0)
    task = asyncio.create_task(supervisor.run())
    await _wait_state(supervisor, "recommendations", "failed")
    await _wait_state(supervisor, "projections", "running")
    failed = _by_name(supervisor)["recommendations"]
    assert failed["reason"] == "worker_object_id_missing"
    assert failed["restarts"] == 0  # not retried
    assert not supervisor.ready
    supervisor.request_shutdown()
    await asyncio.wait_for(task, 5)
    assert _by_name(supervisor)["recommendations"]["state"] == "failed"


async def test_unexpected_clean_exit_is_a_crash() -> None:
    class Quitter:
        async def run(self) -> None:
            return None

        def request_shutdown(self) -> None:
            return None

    async def build(_lifetime: ClientLifetime) -> RoleRunnable:
        return Quitter()

    supervisor = RoleSupervisor({"ingestion": build}, policy=FAST, rng=lambda: 0.0)
    task = asyncio.create_task(supervisor.run())

    await until(lambda: _by_name(supervisor)["ingestion"]["restarts"] >= 2)
    assert _by_name(supervisor)["ingestion"]["reason"] == "exited_unexpectedly"
    supervisor.request_shutdown()
    await asyncio.wait_for(task, 5)


async def test_idle_process_is_ready_and_reports_no_roles() -> None:
    supervisor = RoleSupervisor({})
    health = HealthServer(
        lambda: supervisor.status,
        "127.0.0.1",
        0,
        roles_provider=supervisor.snapshot,
        ready_provider=lambda: supervisor.ready,
    )
    await health.start()
    task = asyncio.create_task(supervisor.run())
    try:
        base = f"http://127.0.0.1:{health.bound_port}"
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{base}/healthz") as resp:
                assert resp.status == 200
                assert await resp.json() == {"status": "ok", "roles": []}
            async with session.get(f"{base}/readyz") as resp:
                assert resp.status == 200
                assert await resp.json() == {"status": "ready", "roles": []}
            supervisor.request_shutdown()
            async with session.get(f"{base}/readyz") as resp:
                assert resp.status == 503
                assert (await resp.json())["status"] == "draining"
    finally:
        await asyncio.wait_for(task, 5)
        await health.stop()


async def test_health_bodies_carry_per_role_liveness_and_readiness() -> None:
    roster = Roster("ingestion", "aggregates")
    supervisor = _supervisor(roster)
    health = HealthServer(
        lambda: supervisor.status,
        "127.0.0.1",
        0,
        roles_provider=supervisor.snapshot,
        ready_provider=lambda: supervisor.ready,
    )
    await health.start()
    task = asyncio.create_task(supervisor.run())
    try:
        await _wait_state(supervisor, "ingestion", "running")
        await _wait_state(supervisor, "aggregates", "running")
        base = f"http://127.0.0.1:{health.bound_port}"
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{base}/readyz") as resp:
                body = await resp.json()
                assert resp.status == 200
                assert body["status"] == "ready"
                assert [r["name"] for r in body["roles"]] == ["ingestion", "aggregates"]
                assert all(r["live"] and r["ready"] for r in body["roles"])
    finally:
        supervisor.request_shutdown()
        await asyncio.wait_for(task, 5)
        await health.stop()
