"""Revocation store port and the in-memory fake used by unit tests and the local sandbox.

Contract for implementations:

* ``get`` returns the entry or ``None`` (never revoked, or retention expired). An unreadable store
  raises ``dependency_transient``; it is never reported as ``None`` (fail closed).
* ``put`` is "latest revocation wins": an existing entry with a later or equal ``revoked_at`` is
  kept and returned; otherwise the new entry is stored and returned. Retention restarts on write.
"""

from __future__ import annotations

import time
from typing import Protocol, runtime_checkable

from neurosphere_core.auth.jwt import Clock
from neurosphere_core.auth.revocation.model import (
    DEFAULT_REVOCATION_RETENTION_SECONDS,
    RevocationEntry,
    revocation_document_id,
)

__all__ = ["InMemoryRevocationStore", "RevocationStore"]


@runtime_checkable
class RevocationStore(Protocol):
    async def get(self, principal_id: str) -> RevocationEntry | None:
        """The principal's current entry, or ``None``. Outage raises ``dependency_transient``."""
        ...

    async def put(self, entry: RevocationEntry) -> RevocationEntry:
        """Store ``entry`` unless a later revocation exists; return the effective entry."""
        ...


class InMemoryRevocationStore:
    """Test double. Never a production store (per-process; no replication).

    ``fail_with`` makes every call raise (outage simulation). Retention is honored against the
    injected clock, mirroring the Cosmos per-item ``ttl``. Calls are counted.
    """

    def __init__(
        self,
        *,
        retention_seconds: float = DEFAULT_REVOCATION_RETENTION_SECONDS,
        clock: Clock = time.time,
    ) -> None:
        self._retention = retention_seconds
        self._clock = clock
        self._entries: dict[str, tuple[RevocationEntry, float]] = {}
        self.error: Exception | None = None
        self.get_calls = 0
        self.put_calls = 0

    def fail_with(self, error: Exception | None) -> None:
        self.error = error

    def _raise_injected_error(self) -> None:
        error = self.error
        if isinstance(error, Exception):
            raise error

    def _live(self, principal_id: str) -> RevocationEntry | None:
        found = self._entries.get(revocation_document_id(principal_id))
        if found is None:
            return None
        entry, expires_at = found
        return entry if self._clock() < expires_at else None

    async def get(self, principal_id: str) -> RevocationEntry | None:
        self.get_calls += 1
        self._raise_injected_error()
        return self._live(principal_id)

    async def put(self, entry: RevocationEntry) -> RevocationEntry:
        self.put_calls += 1
        self._raise_injected_error()
        existing = self._live(entry.principal_id)
        if existing is not None and existing.revoked_at >= entry.revoked_at:
            return existing
        self._entries[revocation_document_id(entry.principal_id)] = (
            entry,
            self._clock() + self._retention,
        )
        return entry
