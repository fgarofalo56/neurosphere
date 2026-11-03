"""In-memory sliding-window rate limiter keyed by client identity."""

from __future__ import annotations

import math
import time
from collections import OrderedDict, deque
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: float,
        max_clients: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._max_clients = max_clients
        self._clock = clock
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()

    def check(self, key: str) -> int | None:
        """Record a request. Returns None if allowed, else seconds until retry (>= 1)."""
        now = self._clock()
        q = self._hits.get(key)
        if q is None:
            q = deque()
            self._hits[key] = q
            while len(self._hits) > self._max_clients:
                self._hits.popitem(last=False)
        else:
            self._hits.move_to_end(key)
        while q and q[0] <= now - self._window:
            q.popleft()
        if len(q) >= self._limit:
            return max(1, math.ceil(q[0] + self._window - now))
        q.append(now)
        return None
