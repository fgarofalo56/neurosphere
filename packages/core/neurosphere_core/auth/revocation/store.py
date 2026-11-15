"""Revocation store port and the in-memory fake used by unit tests and the local sandbox.

Contract for implementations:

* ``get`` returns the entry or ``None`` (never revoked, or retention expired). An unreadable store
  raises ``dependency_transient``; it is never reported as ``None`` (fail closed).
* ``put`` keeps what :func:`~neurosphere_core.auth.revocation.model.merge_entries` decides: an
  active ``until_lifted`` block is never weakened; otherwise the latest ``revoked_at`` wins. The
  effective entry is returned. Retention restarts on write; a blocking entry has no retention
  (it lives until lifted).
* ``lift`` (PRP-39) turns an active block into an ``issued_before`` entry with the same
  ``revoked_at`` and restarts retention. No entry, or an entry that is not blocking, is
  ``not_found`` (reason ``no_active_block``).
"""

from __future__ import annotations

import math
import time
from datetime import datetime
from typing import Protocol, runtime_checkable

from neurosphere_core.auth.jwt import Clock
from neurosphere_core.auth.revocation.model import (
    DEFAULT_REVOCATION_RETENTION_SECONDS,
    RevocationEntry,
    lifted_entry,
    merge_entries,
    revocation_document_id,
)
from neurosphere_core.errors import NotFoundError

__all__ = ["InMemoryRevocationStore", "RevocationReader", "RevocationStore", "no_active_block"]


def no_active_block() -> NotFoundError:
    return NotFoundError("no active revocation block", reason="no_active_block")


@runtime_checkable
class RevocationReader(Protocol):
    """Read side only: what ``CachedRevocationChecker`` needs."""

    async def get(self, principal_id: str) -> RevocationEntry | None:
        """The principal's current entry, or ``None``. Outage raises ``dependency_transient``."""
        ...


@runtime_checkable
class RevocationStore(Protocol):
    async def get(self, principal_id: str) -> RevocationEntry | None:
        """The principal's current entry, or ``None``. Outage raises ``dependency_transient``."""
        ...

    async def put(self, entry: RevocationEntry) -> RevocationEntry:
        """Store ``entry`` unless the existing entry wins; return the effective entry."""
        ...

    async def lift(
        self, principal_id: str, *, lifted_by: str, lifted_at: datetime
    ) -> RevocationEntry:
        """Lift an active block; return the lifted entry. No block -> ``not_found``."""
        ...


class InMemoryRevocationStore:
    """Test double. Never a production store (per-process; no replication).

    ``fail_with`` makes every call raise (outage simulation). Retention is honored against the
    injected clock, mirroring the Cosmos per-item ``ttl`` (none for a blocking entry). Calls are
    counted.
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
        self.lift_calls = 0

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

    def _store(self, entry: RevocationEntry) -> None:
        expires_at = math.inf if entry.blocking else self._clock() + self._retention
        self._entries[revocation_document_id(entry.principal_id)] = (entry, expires_at)

    async def get(self, principal_id: str) -> RevocationEntry | None:
        self.get_calls += 1
        self._raise_injected_error()
        return self._live(principal_id)

    async def put(self, entry: RevocationEntry) -> RevocationEntry:
        self.put_calls += 1
        self._raise_injected_error()
        existing = self._live(entry.principal_id)
        effective = merge_entries(existing, entry)
        if effective is not existing:
            self._store(effective)
        return effective

    async def lift(
        self, principal_id: str, *, lifted_by: str, lifted_at: datetime
    ) -> RevocationEntry:
        self.lift_calls += 1
        self._raise_injected_error()
        existing = self._live(principal_id)
        if existing is None or not existing.blocking:
            raise no_active_block()
        lifted = lifted_entry(existing, lifted_at=lifted_at, lifted_by=lifted_by)
        self._store(lifted)
        return lifted
