"""Request telemetry (PRP-05 G1): ``ns.api.request.*`` SLO metrics and a server span per request.

Labels use the matched route template (``/things/{id}``), never the raw path, so cardinality stays
bounded and ids or other PII in URLs cannot leak into metrics. Requests that match no route are
grouped under one ``unmatched`` label. The correlation id is set on the span as
``ns.correlation_id``; this middleware sits inside ``CorrelationIdMiddleware`` so the id is bound.
"""

from __future__ import annotations

import os
import time
from typing import Final

from neurosphere_core.observability import Telemetry
from opentelemetry.trace import SpanKind, Status, StatusCode
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from neurosphere_api.middleware.correlation import correlation_id_of

UNMATCHED_ROUTE: Final = "unmatched"
_TRACER_NAME: Final = "neurosphere_api.http"


def azure_monitor_connection_string() -> str | None:
    """Explicit opt-in only; ``configure_telemetry`` still ignores it when NS_ENV=local."""
    return os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip() or None


def route_template(scope: Scope) -> str:
    """The matched route's path template, or ``unmatched`` (never the raw request path)."""
    route = scope.get("route")
    path = getattr(route, "path_format", None) or getattr(route, "path", None)
    if not isinstance(path, str) or not path:
        return UNMATCHED_ROUTE
    # FastAPI's include_router(prefix=...) keeps the prefix off ``route.path``. Recover it from
    # the literal request path: it is the part left once the route's own (rendered) template is
    # removed from the end. Any doubt falls back to the route's own template.
    try:
        suffix = path.format(**scope.get("path_params", {}))
        full = str(scope.get("path", ""))[len(str(scope.get("root_path", ""))) :]
        if suffix and full.endswith(suffix):
            prefix = full[: len(full) - len(suffix)]
            if "{" not in prefix and "}" not in prefix:
                return prefix + path
    except (KeyError, IndexError, ValueError):
        pass
    return path


class TelemetryMiddleware:
    def __init__(self, app: ASGIApp, *, telemetry: Telemetry) -> None:
        self.app = app
        self._telemetry = telemetry
        self._tracer = telemetry.tracer(_TRACER_NAME)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = str(scope.get("method", "GET"))
        status = 500  # until a response starts; an escaping exception is an unhandled 500

        async def send_capturing(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        start = time.perf_counter()
        with self._tracer.start_as_current_span(f"HTTP {method}", kind=SpanKind.SERVER) as span:
            span.set_attribute("ns.correlation_id", correlation_id_of(scope))
            span.set_attribute("http.request.method", method)
            try:
                await self.app(scope, receive, send_capturing)
            finally:
                route = route_template(scope)
                span.update_name(f"{method} {route}")
                span.set_attribute("http.route", route)
                span.set_attribute("http.response.status_code", status)
                if status >= 500:
                    span.set_status(Status(StatusCode.ERROR))
                self._telemetry.slo.record_api_request(
                    route=route,
                    method=method,
                    status_code=status,
                    duration_ms=(time.perf_counter() - start) * 1000.0,
                )
