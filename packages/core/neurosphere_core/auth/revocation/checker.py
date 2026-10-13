"""``RevocationChecker`` implementation with a TTL-bounded per-replica cache (PRP-06 C12).

Revocation is bounded by ``NS_REVOCATION_TTL_SECONDS``; it is not instant on every replica. Each
answer is cached for at most ``ttl_seconds``, measured from the moment the store read STARTED
(not when it returned), so a read that raced a revocation write can never be cached past
``revoked_at + ttl_seconds``. Consequences, all tested with a fake clock:

* a replica that cached "not revoked" just before a revocation still allows the principal until
  ``ttl_seconds`` after it started that read, and denies from then on (the TTL boundary);
* ``invalidate_principal`` (registered as a revocation cache hook) makes the revoking replica
  deny immediately;
* on a store error nothing is cached and the error is raised as ``dependency_transient``: an
  outage is never "not revoked". An unexpired entry may still serve during an outage; expiry is
  never extended on error (same rule as the policy cache, C14).

``ScopeDeriver`` maps ``True`` to ``forbidden`` (reason ``principal_revoked``, HTTP 403).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from neurosphere_core.auth.jwt import Clock
from neurosphere_core.auth.revocation.model import (
    DEFAULT_CLOCK_SKEW_SECONDS,
    DEFAULT_REVOCATION_TTL_SECONDS,
    RevocationEntry,
    RevocationSettings,
)
from neurosphere_core.auth.revocation.store import RevocationStore
from neurosphere_core.errors import DependencyTransientError

__all__ = ["DEFAULT_CHECKER_MAX_ENTRIES", "CachedRevocationChecker"]

DEFAULT_CHECKER_MAX_ENTRIES: Final = 10_000


@dataclass(frozen=True, slots=True)
class _Cached:
    revoked_at: datetime | None
    read_started_at: float


class CachedRevocationChecker:
    """Implements ``neurosphere_core.auth.scope.RevocationChecker``."""

    def __init__(
        self,
        store: RevocationStore,
        *,
        ttl_seconds: float = DEFAULT_REVOCATION_TTL_SECONDS,
        clock_skew_seconds: float = DEFAULT_CLOCK_SKEW_SECONDS,
        max_entries: int = DEFAULT_CHECKER_MAX_ENTRIES,
        clock: Clock = time.time,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if clock_skew_seconds < 0:
            raise ValueError("clock_skew_seconds must not be negative")
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self._store = store
        self._ttl = ttl_seconds
        self._skew = timedelta(seconds=clock_skew_seconds)
        self._max = max_entries
        self._clock = clock
        self._cache: dict[str, _Cached] = {}

    @classmethod
    def from_settings(
        cls, store: RevocationStore, settings: RevocationSettings, *, clock: Clock = time.time
    ) -> CachedRevocationChecker:
        return cls(
            store,
            ttl_seconds=settings.ttl_seconds,
            clock_skew_seconds=settings.clock_skew_seconds,
            clock=clock,
        )

    @property
    def ttl_seconds(self) -> float:
        return self._ttl

    async def is_revoked(self, principal_id: str, issued_at: datetime) -> bool:
        """True when ``principal_id`` was revoked at or after ``issued_at`` (minus skew)."""
        if issued_at.tzinfo is None or issued_at.utcoffset() is None:
            raise ValueError("issued_at must be timezone-aware")
        revoked_at = await self._revoked_at(principal_id)
        return revoked_at is not None and issued_at <= revoked_at + self._skew

    def invalidate_principal(self, principal_id: str) -> int:
        """Drop the cached answer for one principal (revocation cache hook)."""
        return 1 if self._cache.pop(principal_id, None) is not None else 0

    def invalidate_all(self) -> None:
        self._cache.clear()

    async def _revoked_at(self, principal_id: str) -> datetime | None:
        started = self._clock()
        cached = self._cache.get(principal_id)
        if cached is not None and cached.read_started_at <= started < (
            cached.read_started_at + self._ttl
        ):
            return cached.revoked_at
        try:
            entry: RevocationEntry | None = await self._store.get(principal_id)
        except DependencyTransientError:
            raise
        except Exception as exc:
            raise DependencyTransientError(
                "revocation store unavailable", reason="revocation_store_unavailable"
            ) from exc
        if entry is not None and (
            not isinstance(entry, RevocationEntry) or entry.principal_id != principal_id
        ):
            raise DependencyTransientError(
                "revocation store returned an invalid entry",
                reason="revocation_entry_invalid",
                upstream_invalid=True,
            )
        revoked_at = None if entry is None else entry.revoked_at
        self._cache.pop(principal_id, None)
        self._cache[principal_id] = _Cached(revoked_at, started)
        while len(self._cache) > self._max:
            del self._cache[next(iter(self._cache))]
        return revoked_at
