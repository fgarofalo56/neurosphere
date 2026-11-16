"""Shared plumbing for the detection readers (PRP-61 item 3).

Read-only by construction: the only verbs are GET and the Resource Graph query POST. Errors map
to a machine reason by status code; no token, URL query, request body or response body is placed
in a reason or a log line.
"""

from __future__ import annotations

import re
from typing import Any, Final, Protocol

import httpx
from neurosphere_core.detections import ReadStatus

__all__ = [
    "GUID",
    "ReadError",
    "TokenSource",
    "reason_for_status",
    "send",
]

GUID: Final = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class TokenSource(Protocol):
    """The slice of an async credential the readers use."""

    async def get_token(self, *scopes: str, **kwargs: Any) -> Any: ...


class ReadError(Exception):
    """A read that did not finish. ``reason`` is a machine code; ``status`` the read status."""

    def __init__(self, reason: str, status: ReadStatus = "unreadable") -> None:
        super().__init__(reason)
        self.reason = reason
        self.status: ReadStatus = status


def reason_for_status(code: int) -> str:
    if code in (401, 403):
        return "forbidden"
    if code == 404:
        return "not_found"
    if code == 429:
        return "throttled"
    if code >= 500:
        return "upstream_unavailable"
    return "rejected"


async def send(
    client: httpx.AsyncClient,
    credential: TokenSource,
    scope: str,
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One authenticated request; returns the JSON object body or raises :class:`ReadError`."""
    if method not in ("GET", "POST"):  # defence in depth: no write verb can be sent from here
        raise ReadError("method_refused")
    try:
        token = await credential.get_token(scope)
    except Exception:
        raise ReadError("token_unavailable") from None
    headers = {"Authorization": f"Bearer {token.token}", "Accept": "application/json"}
    try:
        if method == "GET":
            response = await client.get(url, headers=headers)
        else:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.HTTPError:
        raise ReadError("unreachable") from None
    if response.status_code >= 300:
        raise ReadError(reason_for_status(response.status_code))
    try:
        body = response.json()
    except ValueError:
        raise ReadError("invalid_body") from None
    if not isinstance(body, dict):
        raise ReadError("invalid_body")
    return {str(k): v for k, v in body.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
