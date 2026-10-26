"""The ``python -m neurosphere_workers.runtime`` entrypoint and the ingestion alias."""

from __future__ import annotations

import asyncio
import socket
from typing import Any

import aiohttp
import pytest
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.cloud import Settings
from neurosphere_workers.ingestion import __main__ as ingestion_main
from neurosphere_workers.runtime import __main__ as runtime_main
from neurosphere_workers.runtime.factories import RoleBuilder, RuntimeConfig
from neurosphere_workers.runtime.settings import AuthSettings, StoreSettings, WorkerSettings
from neurosphere_workers.runtime.supervisor import RoleRunnable

from .test_supervisor import FakeRole


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _config(port: int) -> RuntimeConfig:
    return RuntimeConfig(
        Settings(env="local"), WorkerSettings(health_port=port), StoreSettings(), AuthSettings()
    )


def test_unknown_role_refuses_start(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[Any] = []
    monkeypatch.setattr(runtime_main, "_amain", lambda raw: called.append(raw))
    assert runtime_main.main("ingestion,bogus") == runtime_main.EXIT_USAGE
    monkeypatch.setenv("NS_WORKER_ROLES", "nope")
    assert runtime_main.main() == runtime_main.EXIT_USAGE
    assert called == []  # nothing was started


def test_ingestion_module_is_an_alias_for_the_ingestion_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str | None] = []

    def fake_main(raw_roles: str | None = None) -> int:
        seen.append(raw_roles)
        return 0

    monkeypatch.setattr(ingestion_main, "runtime_main", fake_main)
    assert ingestion_main.main() == 0
    assert seen == ["ingestion"]


async def _get_json(url: str, *, until_ok: bool = True) -> tuple[int, Any]:
    async def attempt() -> tuple[int, Any]:
        async with aiohttp.ClientSession() as session, session.get(url) as resp:
            return resp.status, await resp.json()

    if not until_ok:
        return await attempt()
    for _ in range(200):  # the server binds right after the task starts
        try:
            return await attempt()
        except aiohttp.ClientConnectionError:
            await asyncio.sleep(0.02)
    raise AssertionError("health endpoint never came up")


async def test_idle_run_serves_health_with_no_roles() -> None:
    port = _free_port()
    stop = asyncio.Event()
    task = asyncio.create_task(
        runtime_main.run_roles((), _config(port), handle_signals=False, stop=stop)
    )
    status, body = await _get_json(f"http://127.0.0.1:{port}/healthz")
    assert (status, body) == (200, {"status": "ok", "roles": []})
    status, body = await _get_json(f"http://127.0.0.1:{port}/readyz", until_ok=False)
    assert (status, body) == (200, {"status": "ready", "roles": []})
    stop.set()
    assert await asyncio.wait_for(task, 5) == 0


async def test_configured_roles_run_through_the_supervisor_and_report_readiness() -> None:
    port = _free_port()
    built: dict[str, FakeRole] = {}

    def builder(name: str) -> RoleBuilder:
        async def build(_cfg: RuntimeConfig, _lifetime: ClientLifetime) -> RoleRunnable:
            built[name] = FakeRole()
            return built[name]

        return build

    builders = {n: builder(n) for n in ("ingestion", "aggregates")}
    stop = asyncio.Event()
    task = asyncio.create_task(
        runtime_main.run_roles(
            ("ingestion", "aggregates"),
            _config(port),
            builders=builders,
            handle_signals=False,
            stop=stop,
        )
    )
    status, body = 0, {}
    for _ in range(500):
        status, body = await _get_json(f"http://127.0.0.1:{port}/readyz")
        if status == 200:
            break
        await asyncio.sleep(0.01)
    assert status == 200
    assert [r["name"] for r in body["roles"]] == ["ingestion", "aggregates"]
    assert {r["state"] for r in body["roles"]} == {"running"}
    stop.set()
    assert await asyncio.wait_for(task, 5) == 0
    assert all(role.stopped.is_set() for role in built.values())


@pytest.mark.parametrize(
    ("level", "expected"), [("", "WARNING"), ("INFO", "WARNING"), ("DEBUG", None)]
)
def test_azure_loggers_are_quiet_unless_debug(
    monkeypatch: pytest.MonkeyPatch, level: str, expected: str | None
) -> None:
    import logging

    azure_logger = logging.getLogger("azure")
    previous = azure_logger.level
    try:
        azure_logger.setLevel(logging.NOTSET)
        monkeypatch.setenv("NS_LOG_LEVEL", level)
        monkeypatch.setattr(runtime_main, "_amain", lambda raw: asyncio.sleep(0, 0))
        monkeypatch.setattr(runtime_main.asyncio, "run", lambda coro: (coro.close(), 0)[1])
        runtime_main.main("")
        want = logging.NOTSET if expected is None else logging.getLevelName(expected)
        assert azure_logger.level == want
    finally:
        azure_logger.setLevel(previous)
