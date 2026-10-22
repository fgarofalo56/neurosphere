"""Shared HTTP plumbing for the REST adapters: token, SSE framing, error translation.

Credentials are managed identity (or any caller-supplied ``AsyncTokenCredential``) only; this
module never accepts, stores or logs a raw key. Redirects are never followed, so a bearer
token cannot be replayed at another host. Error details carry the status code only.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Final

import httpx
from azure.core.credentials_async import AsyncTokenCredential

from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    NeuroSphereError,
    RateLimitedError,
    UnauthorizedError,
)

REQUEST_TIMEOUT: Final = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)
_DEFAULT_RETRY_AFTER: Final = 5


async def bearer_headers(
    credential: AsyncTokenCredential, scope: str, correlation_id: str
) -> dict[str, str]:
    """Authorization headers from a managed-identity token (never logged)."""
    try:
        token = await credential.get_token(scope)
    except Exception as exc:
        raise DependencyTransientError(
            "model endpoint token acquisition failed", reason="token_unavailable"
        ) from exc
    return {
        "Authorization": f"Bearer {token.token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "x-ms-client-request-id": correlation_id,
    }


def error_for_status(response: httpx.Response) -> NeuroSphereError:
    """Translate a non-2xx model response into the taxonomy without echoing its body."""
    status = response.status_code
    if status == 401:
        return UnauthorizedError("model endpoint rejected the identity", reason="model_auth")
    if status == 403:
        return ForbiddenError("model endpoint denied access", reason="model_auth")
    if status == 429:
        raw = response.headers.get("retry-after", "")
        retry = int(raw) if raw.isdigit() else _DEFAULT_RETRY_AFTER
        return RateLimitedError(retry, "model endpoint is rate limiting", reason="model_throttled")
    if status >= 500:
        return DependencyTransientError(
            f"model endpoint unavailable (HTTP {status})", reason="model_unavailable"
        )
    return DependencyTransientError(
        f"model endpoint rejected the request (HTTP {status})",
        reason="model_request_rejected",
        upstream_invalid=True,
    )


async def sse_data(response: httpx.Response) -> AsyncIterator[str]:
    """Yield the payload of each ``data:`` line of a server-sent-event stream."""
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            yield line[5:].strip()
