"""ASGI admission middleware factory (PRP-21 item 2).

The middleware never reads a domain from headers, query or body. It asks two injected
callables: ``scope_of`` (the server-derived ``IdentityScope`` for this request, set by auth
middleware upstream) and optionally ``route_domain_of`` (a domain resolved from the route, which
is validated against the scope before it is trusted). No scope means 401: fail closed.

Errors render as ``application/problem+json`` using the taxonomy's ``to_problem_details`` and a
``Retry-After`` header, matching ``neurosphere_api.middleware.problem`` (core cannot import the
services, so the few lines of rendering are mirrored here).
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from neurosphere_core.admission.limiter import TokenBucketLimiter, derive_limiter_key
from neurosphere_core.errors import NeuroSphereError, RateLimitedError, UnauthorizedError
from neurosphere_core.scope import IdentityScope

# Plain ASGI aliases: core does not depend on starlette.
Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

CORRELATION_HEADER = "x-correlation-id"
BACKPRESSURE_HEADER = "x-ns-backpressure"
_PROBLEM_MEDIA_TYPE = "application/problem+json"
_VALID_CID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

ScopeResolver = Callable[[Scope], IdentityScope | None]
RouteDomainResolver = Callable[[Scope], str | None]


def scope_from_state(scope: Scope) -> IdentityScope | None:
    """Default resolver: ``scope["state"]["identity_scope"]`` set by upstream auth."""
    state: dict[str, Any] = scope.get("state") or {}
    value = state.get("identity_scope")
    return value if isinstance(value, IdentityScope) else None


def _correlation_id(scope: Scope) -> str:
    state: dict[str, Any] = scope.get("state") or {}
    value = state.get("correlation_id")
    if isinstance(value, str) and _VALID_CID.fullmatch(value):
        return value
    return str(uuid.uuid4())


async def _send_problem(error: NeuroSphereError, scope: Scope, send: Send) -> None:
    cid = _correlation_id(scope)
    body = error.to_problem_details(cid, instance=str(scope.get("path", "")))
    payload = json.dumps(body.model_dump(mode="json", exclude_none=True)).encode()
    headers = [
        (b"content-type", _PROBLEM_MEDIA_TYPE.encode()),
        (b"content-length", str(len(payload)).encode()),
        (CORRELATION_HEADER.encode(), cid.encode()),
    ]
    if error.retry_after_seconds is not None:
        headers.append((b"retry-after", str(error.retry_after_seconds).encode()))
    await send({"type": "http.response.start", "status": error.status, "headers": headers})
    await send({"type": "http.response.body", "body": payload})


class AdmissionMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: TokenBucketLimiter,
        scope_of: ScopeResolver = scope_from_state,
        route_domain_of: RouteDomainResolver | None = None,
        exempt_paths: frozenset[str] = frozenset(),
    ) -> None:
        self.app = app
        self._limiter = limiter
        self._scope_of = scope_of
        self._route_domain_of = route_domain_of
        self._exempt = exempt_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in self._exempt:
            await self.app(scope, receive, send)
            return
        identity = self._scope_of(scope)
        if identity is None:
            await _send_problem(UnauthorizedError(), scope, send)
            return
        route_domain = self._route_domain_of(scope) if self._route_domain_of else None
        key = derive_limiter_key(identity, route_domain)
        try:
            signal = self._limiter.admit(key)
        except RateLimitedError as exc:
            await _send_problem(exc, scope, send)
            return

        async def send_with_signal(message: Message) -> None:
            if message["type"] == "http.response.start" and signal.level != "ok":
                headers = list(message.get("headers", []))
                headers.append((BACKPRESSURE_HEADER.encode(), signal.level.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_signal)


def admission_middleware(
    limiter: TokenBucketLimiter,
    *,
    scope_of: ScopeResolver = scope_from_state,
    route_domain_of: RouteDomainResolver | None = None,
    exempt_paths: frozenset[str] = frozenset(),
) -> Callable[[ASGIApp], ASGIApp]:
    """Factory returning an ASGI wrapper: ``app = admission_middleware(limiter)(app)``."""

    def wrap(app: ASGIApp) -> ASGIApp:
        return AdmissionMiddleware(
            app,
            limiter=limiter,
            scope_of=scope_of,
            route_domain_of=route_domain_of,
            exempt_paths=exempt_paths,
        )

    return wrap
