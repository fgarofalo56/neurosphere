"""Correlation ID middleware (PRP-05 C7): accept a valid caller value, else generate a UUID4."""

from __future__ import annotations

import re
import uuid
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CORRELATION_HEADER = "x-correlation-id"
_VALID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def correlation_id_of(scope: Scope) -> str:
    """Correlation id bound to this request (a fresh UUID4 if the middleware has not run)."""
    state: dict[str, Any] = scope.setdefault("state", {})
    value = state.get("correlation_id")
    if not isinstance(value, str):
        value = str(uuid.uuid4())
        state["correlation_id"] = value
    return value


def _tag_span(correlation_id: str) -> None:
    try:
        from opentelemetry import trace
    except ImportError:  # OTel is optional at this layer
        return
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attribute("ns.correlation_id", correlation_id)


class CorrelationIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        supplied = ""
        for name, value in scope.get("headers", []):
            if name == CORRELATION_HEADER.encode():
                supplied = value.decode("latin-1")
                break
        state: dict[str, Any] = scope.setdefault("state", {})
        cid = supplied if _VALID.fullmatch(supplied) else str(uuid.uuid4())
        state["correlation_id"] = cid
        _tag_span(cid)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers[CORRELATION_HEADER] = cid
            await send(message)

        await self.app(scope, receive, send_with_header)
