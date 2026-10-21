"""Realtime router (PRP-18 item 1): ``/api/v1/realtime/ws``.

The route authenticates inside the gateway (a WebSocket handshake cannot use the HTTP
``require`` dependency, which reads a ``Request``). ``_data_read_marker`` carries the PRP-06
permission marker so the route inventory (``authz.routes``) sees ``data.read`` declared; the
actual per-domain check runs in the gateway on every subscribe and every delta.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Final

from fastapi import APIRouter, Depends, WebSocket
from neurosphere_core.auth.scope import Permission
from starlette.requests import HTTPConnection

from neurosphere_api.authz.dependencies import PERMISSION_MARKER
from neurosphere_api.realtime.gateway import serve
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "build_router", "register"]

PREFIX: Final = "/api/v1/realtime"


def _data_read_marker(connection: HTTPConnection) -> None:
    """Declares ``data.read`` for the route inventory; enforcement happens in the gateway."""
    return None


setattr(_data_read_marker, PERMISSION_MARKER, Permission.DATA_READ)


def build_router() -> APIRouter:
    router = APIRouter(tags=["realtime"])

    @router.websocket("/ws", dependencies=[Depends(_data_read_marker)])
    async def realtime_ws(websocket: WebSocket) -> None:
        await serve(websocket)

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
