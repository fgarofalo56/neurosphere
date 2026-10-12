"""Request size limit. Oversize bodies are an ``invalid_schema`` (422) problem, not a new code.

The PRP-01 taxonomy has no 413 (C13: reuse names only), so the body states the limit in
``detail`` and ``reason`` is ``request_too_large``.
"""

from __future__ import annotations

from neurosphere_core.errors import InvalidSchemaError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from neurosphere_api.middleware.correlation import correlation_id_of
from neurosphere_api.middleware.problem import problem_response

DEFAULT_MAX_REQUEST_BYTES = 1024 * 1024


class RequestTooLargeError(InvalidSchemaError):
    def __init__(self, limit: int) -> None:
        super().__init__(f"Request body exceeds {limit} bytes.", reason="request_too_large")


class RequestSizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int = DEFAULT_MAX_REQUEST_BYTES) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    break
                if declared > self.max_bytes:
                    response = problem_response(
                        RequestTooLargeError(self.max_bytes),
                        correlation_id_of(scope),
                        scope["path"],
                    )
                    await response(scope, receive, send)
                    return
                break

        seen = 0
        limit = self.max_bytes

        async def limited_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise RequestTooLargeError(limit)
            return message

        await self.app(scope, limited_receive, send)
