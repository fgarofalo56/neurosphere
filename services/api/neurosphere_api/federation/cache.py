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

__all__ = ["HARD_MAX_TTL_SECONDS", "MAX_TTL_SECONDS", "SummaryCache", "summary_cache_key"]

MAX_TTL_SECONDS: Final = 300.0  # default ceiling; NS_FEDERATION_CACHE_MAX_TTL_SECONDS overrides
HARD_MAX_TTL_SECONDS: Final = 3600.0  # ceiling of the ceiling: staleness stays bounded
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
        max_ttl_seconds: float = MAX_TTL_SECONDS,
    ) -> None:
        if not 0 < max_ttl_seconds <= HARD_MAX_TTL_SECONDS:
            raise ValueError(f"max_ttl_seconds must be in (0, {HARD_MAX_TTL_SECONDS}]")
        if not 0 < ttl_seconds <= max_ttl_seconds:
            raise ValueError(f"ttl_seconds must be in (0, {max_ttl_seconds}]")
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
        # Every entry has the same TTL, so insertion order is expiry order: evict from the front
        # instead of rebuilding the dict on each write. Re-inserting a key moves it to the back.
        now = self._clock()
        self._entries.pop(key, None)
        while self._entries:
            oldest = next(iter(self._entries))
            if self._entries[oldest][0] > now and len(self._entries) < self._max:
                break
            del self._entries[oldest]
        self._entries[key] = (now + self._ttl, value)
