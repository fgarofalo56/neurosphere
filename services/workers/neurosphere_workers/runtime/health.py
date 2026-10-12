"""Lightweight health endpoint for the worker process."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from aiohttp import web

HealthStatus = Literal["ok", "draining"]


class HealthServer:
    """Serves ``GET /healthz`` as ``{"status": "ok" | "draining"}`` (HTTP 200 for both).

    Draining is still alive, so liveness probes must not restart the process mid-drain.
    """

    def __init__(
        self, status_provider: Callable[[], HealthStatus], host: str = "127.0.0.1", port: int = 0
    ) -> None:
        self._status_provider = status_provider
        self._host = host
        self._port = port
        self._runner: web.AppRunner | None = None
        self.bound_port: int = port

    async def _healthz(self, _request: web.Request) -> web.Response:
        return web.json_response({"status": self._status_provider()})

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/healthz", self._healthz)
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
