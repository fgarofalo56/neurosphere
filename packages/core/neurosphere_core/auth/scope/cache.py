"""Short in-process TTL cache for policy documents (PRP-06 C14).

Rules: an entry is served only while ``loaded_at <= now < expires_at`` (a clock that moves
backwards also invalidates it). A miss or an expired entry calls the loader; if the loader raises,
the exception propagates, the old entry is left exactly as it was (its expiry is never extended)
and nothing is served from it. Values are cached including ``None`` (a missing document), so a
negative answer is as short-lived as a positive one. Size is bounded; the oldest entry goes first.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass

from neurosphere_core.auth.jwt import Clock

__all__ = ["TtlCache"]


@dataclass(frozen=True, slots=True)
class _Entry[V]:
    value: V
    loaded_at: float
    expires_at: float


class TtlCache[K: Hashable, V]:
    def __init__(self, *, ttl_seconds: float, max_entries: int, clock: Clock) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self._ttl = ttl_seconds
        self._max = max_entries
        self._clock = clock
        self._entries: dict[K, _Entry[V]] = {}

    def __len__(self) -> int:
        return len(self._entries)

    async def get_or_load(self, key: K, loader: Callable[[], Awaitable[V]]) -> V:
        now = self._clock()
        entry = self._entries.get(key)
        if entry is not None and entry.loaded_at <= now < entry.expires_at:
            return entry.value
        value = await loader()
        loaded_at = self._clock()
        self._entries.pop(key, None)
        self._entries[key] = _Entry(value, loaded_at, loaded_at + self._ttl)
        while len(self._entries) > self._max:
            del self._entries[next(iter(self._entries))]
        return value

    def expires_at(self, key: K) -> float | None:
        entry = self._entries.get(key)
        return None if entry is None else entry.expires_at

    def discard_where(self, predicate: Callable[[K], bool]) -> int:
        doomed = [k for k in self._entries if predicate(k)]
        for k in doomed:
            del self._entries[k]
        return len(doomed)

    def clear(self) -> None:
        self._entries.clear()
