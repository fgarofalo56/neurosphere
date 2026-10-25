"""Lightweight health endpoints for the worker process.

* ``GET /healthz`` (process liveness): ``{"status": "ok" | "draining", "roles": [...]}``, HTTP 200
  for both. Draining is still alive, so liveness probes must not restart the process mid-drain.
* ``GET /readyz`` (readiness): ``{"status": "ready" | "not_ready" | "draining", "roles": [...]}``.
  HTTP 200 only when ``ready``. With no roles configured (idle) the process is ready and
  ``roles`` is ``[]``.

``roles`` carries one entry per configured role (name, state, live, ready, restarts, a machine
reason code); never a message that could echo data.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Literal

from aiohttp import web

HealthStatus = Literal["ok", "draining"]
RolesProvider = Callable[[], Sequence[dict[str, Any]]]
ReadyProvider = Callable[[], bool]


class HealthServer:
    def __init__(
        self,
        status_provider: Callable[[], HealthStatus],
        host: str = "127.0.0.1",
        port: int = 0,
        *,
        roles_provider: RolesProvider | None = None,
        ready_provider: ReadyProvider | None = None,
    ) -> None:
        self._status_provider = status_provider
        self._roles_provider = roles_provider
        self._ready_provider = ready_provider
        self._host = host
        self._port = port
        self._runner: web.AppRunner | None = None
        self.bound_port: int = port

    def _roles(self) -> list[dict[str, Any]]:
        return [] if self._roles_provider is None else [dict(r) for r in self._roles_provider()]

    async def _healthz(self, _request: web.Request) -> web.Response:
        return web.json_response({"status": self._status_provider(), "roles": self._roles()})

    async def _readyz(self, _request: web.Request) -> web.Response:
        if self._status_provider() == "draining":
            status, code = "draining", 503
        elif self._ready_provider is None or self._ready_provider():
            status, code = "ready", 200
        else:
            status, code = "not_ready", 503
        return web.json_response({"status": status, "roles": self._roles()}, status=code)

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/healthz", self._healthz)
        app.router.add_get("/readyz", self._readyz)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, self._host, self._port)
        await site.start()
        for sock in runner.addresses:
            self.bound_port = int(sock[1])
            break
        self._runner = runner

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
