"""PRP-137 criterion 8: resolution counters appear in the supervisor snapshot (``/readyz``)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from neurosphere_core.clients import ClientLifetime
from neurosphere_workers.agent_identity.wiring import CountersRole
from neurosphere_workers.runtime import BackoffPolicy, RoleSupervisor
from neurosphere_workers.runtime.adapters import IdleRole
from neurosphere_workers.runtime.supervisor import RoleFactory, RoleRunnable

FAST = BackoffPolicy(base_delay_seconds=0.01, max_delay_seconds=0.01)


class _Role:
    def __init__(self) -> None:
        self._stop = asyncio.Event()

    async def run(self) -> None:
        await self._stop.wait()

    def request_shutdown(self) -> None:
        self._stop.set()


def _factory(build: Callable[[], RoleRunnable]) -> RoleFactory:
    async def make(_lifetime: ClientLifetime) -> RoleRunnable:
        return build()

    return make


async def _until(predicate: Callable[[], bool]) -> None:
    async def poll() -> None:  # bounded by wait_for; same 5 ms step as test_supervisor.until
        for _ in range(1000):
            if predicate():
                return
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), 5)


def _by_name(supervisor: RoleSupervisor) -> dict[str, dict[str, Any]]:
    return {r["name"]: r for r in supervisor.snapshot()}


def _broken() -> dict[str, int]:
    raise RuntimeError("store down")


async def test_counters_role_reports_counters_and_plain_roles_do_not() -> None:
    counts = {"resolved_alias": 0, "derived": 0}
    supervisor = RoleSupervisor(
        {
            "aggregates": _factory(lambda: CountersRole(_Role(), lambda: dict(counts))),
            "ingestion": _factory(_Role),
            "evaluation": _factory(lambda: CountersRole(_Role(), _broken)),
        },
        policy=FAST,
        rng=lambda: 0.0,
    )
    task = asyncio.create_task(supervisor.run())
    await _until(lambda: all(r["state"] == "running" for r in supervisor.snapshot()))

    counts["derived"] = 3
    roles = _by_name(supervisor)
    assert roles["aggregates"]["counters"] == {"resolved_alias": 0, "derived": 3}
    assert "counters" not in roles["ingestion"]
    # A failing counters read never breaks the status read or readiness.
    assert "counters" not in roles["evaluation"]
    assert supervisor.ready

    supervisor.request_shutdown()
    await asyncio.wait_for(task, 5)


async def test_wrapping_an_idle_role_keeps_it_idle() -> None:
    supervisor = RoleSupervisor(
        {"projections": _factory(lambda: CountersRole(IdleRole("not_configured"), dict))},
        policy=FAST,
        rng=lambda: 0.0,
    )
    task = asyncio.create_task(supervisor.run())
    await _until(lambda: _by_name(supervisor)["projections"]["state"] == "idle")
    entry = _by_name(supervisor)["projections"]
    assert entry["reason"] == "not_configured"
    assert entry["counters"] == {}

    supervisor.request_shutdown()
    await asyncio.wait_for(task, 5)
