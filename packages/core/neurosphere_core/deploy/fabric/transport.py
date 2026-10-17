"""Transport seam for the Fabric adapter.

Only the protocol and a recording stub live in core. ``httpx`` is not a dependency of
``neurosphere-core``, so the real bearer-token transport (an injected ``AsyncTokenCredential``
using ``FabricEndpoints.token_scope`` for the Fabric host and the ARM scope for the management
host) belongs to the API/worker layer.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class FabricResponse:
    """Minimal response: status, lower-cased headers, parsed JSON body (or None)."""

    status_code: int
    body: Mapping[str, Any] | None = None
    headers: Mapping[str, str] = field(default_factory=dict)

    def header(self, name: str) -> str | None:
        wanted = name.lower()
        for key, value in self.headers.items():
            if key.lower() == wanted:
                return value
        return None


class FabricHttp(Protocol):
    async def request(
        self, method: str, url: str, json: Mapping[str, Any] | None = None
    ) -> FabricResponse: ...


@dataclass(frozen=True)
class RecordedCall:
    method: str
    url: str
    json: Mapping[str, Any] | None


class RecordingFabricHttp:
    """Scripted stub: replays queued responses in order and records every call."""

    def __init__(self, responses: list[FabricResponse] | None = None) -> None:
        self._queue: deque[FabricResponse] = deque(responses or [])
        self.calls: list[RecordedCall] = []

    def enqueue(self, *responses: FabricResponse) -> None:
        self._queue.extend(responses)

    async def request(
        self, method: str, url: str, json: Mapping[str, Any] | None = None
    ) -> FabricResponse:
        self.calls.append(RecordedCall(method, url, json))
        if not self._queue:
            raise AssertionError(f"unscripted call {method} {url}")
        return self._queue.popleft()
