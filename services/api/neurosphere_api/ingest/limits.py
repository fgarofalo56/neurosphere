"""Edge limits: streamed body cap, nesting cap (both before parsing) and per-producer throttle."""

from __future__ import annotations

import math
import time
from collections.abc import AsyncIterator, Callable

from neurosphere_core.errors import InvalidSchemaError, RateLimitedError
from neurosphere_core.payload import raw_json_exceeds_depth

from neurosphere_api.ingest.reasons import ReasonCode


async def read_limited(stream: AsyncIterator[bytes], max_bytes: int) -> bytes:
    """Collect the request stream, failing as soon as the running size passes ``max_bytes``."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in stream:
        total += len(chunk)
        if total > max_bytes:
            raise InvalidSchemaError(
                f"Request body exceeds {max_bytes} bytes.", reason=ReasonCode.BODY_TOO_LARGE
            )
        chunks.append(chunk)
    return b"".join(chunks)


def check_declared_length(content_length: str | None, max_bytes: int) -> None:
    """Cheap early reject on a declared Content-Length; the streamed count is authoritative."""
    if content_length is None:
        return
    try:
        declared = int(content_length)
    except ValueError:
        return
    if declared > max_bytes:
        raise InvalidSchemaError(
            f"Request body exceeds {max_bytes} bytes.", reason=ReasonCode.BODY_TOO_LARGE
        )


def check_depth(raw: bytes, max_depth: int) -> None:
    """Scan raw bytes for nesting depth; must run before ``json.loads``."""
    if raw_json_exceeds_depth(raw, max_depth):
        raise InvalidSchemaError(
            f"JSON nesting exceeds depth {max_depth}.", reason=ReasonCode.DEPTH_EXCEEDED
        )


class TokenBucketLimiter:
    """In-process per-key token bucket. ``clock`` is injectable (monotonic seconds)."""

    def __init__(
        self,
        rate_per_second: float,
        burst: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if rate_per_second <= 0 or burst <= 0:
            raise ValueError("rate_per_second and burst must be positive")
        self._rate = rate_per_second
        self._burst = float(burst)
        self._clock = clock
        self._state: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_seen)

    def acquire(self, key: str) -> None:
        now = self._clock()
        tokens, last = self._state.get(key, (self._burst, now))
        tokens = min(self._burst, tokens + max(0.0, now - last) * self._rate)
        if tokens < 1.0:
            self._state[key] = (tokens, now)
            wait = max(1, math.ceil((1.0 - tokens) / self._rate))
            raise RateLimitedError(
                wait, "Producer rate limit exceeded.", reason=ReasonCode.RATE_LIMITED
            )
        self._state[key] = (tokens - 1.0, now)
