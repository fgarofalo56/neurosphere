"""Server-side scan results: issued by the scan service, consumed by the planner (#36).

In-memory, per process. Each entry is bound to the creating caller (customer, principal
pseudonym, scope hash - all taken from the server-derived ``IdentityScope``) and expires after a
TTL. A lookup by any other caller is refused with ``forbidden``; an unknown or expired id is a
typed ``invalid_schema`` error whose reason says which. The taxonomy has no 404/410 code, so the
422 carries ``scan_not_found`` / ``scan_expired``.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from neurosphere_core.errors import ForbiddenError, InvalidSchemaError
from neurosphere_core.scope import IdentityScope

from neurosphere_api.deploy.scan.models import ScanResponse

SCAN_ID_PATTERN = r"^scan-[0-9a-f]{32}$"
_MAX_ENTRIES = 1000


def owner_key(scope: IdentityScope) -> tuple[str, str, str]:
    principal = scope.to_contract().principal.principal_pseudonym
    return (scope.customer_id, principal, scope.scope_hash)


@dataclass(frozen=True)
class _Entry:
    owner: tuple[str, str, str]
    response: ScanResponse
    expires_at: datetime


class ScanStore:
    def __init__(
        self,
        ttl_seconds: float,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._clock = clock
        self._entries: dict[str, _Entry] = {}
        # Ids that existed and were evicted by expiry, so "expired" and "unknown" differ.
        self._expired: dict[str, None] = {}

    def _sweep(self, now: datetime) -> None:
        for scan_id in [k for k, e in self._entries.items() if e.expires_at <= now]:
            del self._entries[scan_id]
            self._expired[scan_id] = None
        while len(self._expired) > _MAX_ENTRIES:
            del self._expired[next(iter(self._expired))]

    def issue(self, scope: IdentityScope, response: ScanResponse) -> ScanResponse:
        """Store ``response`` under a fresh id and return a copy carrying that id."""
        now = self._clock()
        self._sweep(now)
        while len(self._entries) >= _MAX_ENTRIES:
            del self._entries[next(iter(self._entries))]
        scan_id = f"scan-{secrets.token_hex(16)}"
        stored = response.model_copy(update={"scan_id": scan_id})
        self._entries[scan_id] = _Entry(owner_key(scope), stored, now + self._ttl)
        return stored

    def get(self, scope: IdentityScope, scan_id: str) -> ScanResponse:
        now = self._clock()
        self._sweep(now)
        entry = self._entries.get(scan_id)
        if entry is None:
            if scan_id in self._expired:
                raise InvalidSchemaError(
                    "the scan has expired; run a new scan", reason="scan_expired"
                )
            raise InvalidSchemaError("unknown scan id", reason="scan_not_found")
        if entry.owner != owner_key(scope):
            raise ForbiddenError("the scan was not created by the caller", reason="scan_not_owned")
        return entry.response
