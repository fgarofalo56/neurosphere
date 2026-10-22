"""Small in-process TTL cache for merged summaries (PRP-21 item 3).

Keys MUST be built with :func:`summary_cache_key`, which starts from ``scope_cache_key`` (the scope
hash is part of the key), so two principals with different scopes never share an entry. The cache
is only consulted AFTER ``require`` has authenticated the request and checked revocation, so a
revoked principal gets 403 regardless of what is cached: the TTL bounds staleness of the DATA, not
of the authorization decision.
"""

import time
from collections.abc import Callable, Sequence
from typing import Final

from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import scope_cache_key
from neurosphere_api.federation.models import MergedSummary

__all__ = ["MAX_TTL_SECONDS", "SummaryCache", "summary_cache_key"]

MAX_TTL_SECONDS: Final = 300.0
_MAX_ENTRIES: Final = 1024
NAMESPACE: Final = "federation-summary"


def summary_cache_key(scope: IdentityScope, *, days: int, cell_ids: Sequence[str]) -> str:
    base = scope_cache_key(scope, namespace=NAMESPACE)
    return f"{base}:d={days}:c={','.join(sorted(cell_ids))}"


class SummaryCache:
    def __init__(
        self,
        ttl_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_entries: int = _MAX_ENTRIES,
    ) -> None:
        if not 0 < ttl_seconds <= MAX_TTL_SECONDS:
            raise ValueError(f"ttl_seconds must be in (0, {MAX_TTL_SECONDS}]")
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self._ttl = ttl_seconds
        self._clock = clock
        self._max = max_entries
        self._entries: dict[str, tuple[float, MergedSummary]] = {}

    @property
    def ttl_seconds(self) -> float:
        return self._ttl

    def get(self, key: str) -> MergedSummary | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires, value = entry
        if self._clock() >= expires:
            del self._entries[key]
            return None
        return value

    def put(self, key: str, value: MergedSummary) -> None:
        now = self._clock()
        self._entries = {k: v for k, v in self._entries.items() if v[0] > now}
        while len(self._entries) >= self._max:
            del self._entries[next(iter(self._entries))]
        self._entries[key] = (now + self._ttl, value)
