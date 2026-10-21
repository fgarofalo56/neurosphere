"""Intent store port and the in-memory implementation (tests and the local sandbox).

Contract for every implementation (``CosmosIntentStore`` in ``neurosphere_core.actions.
cosmos_store`` is the durable one):

* ``create`` is idempotent per ``(principal_id, idempotency_key)``. Same scope and same
  ``payload_digest`` returns the ORIGINAL stored intent with ``created=False`` and writes nothing;
  same scope with a different digest raises ``invalid_schema`` reason ``idempotency_key_reused``.
* ``get`` returns ``None`` only for "no such intent in that partition".
* ``replace`` is ETag-conditional: a mismatch (or a vanished document) raises ``stale_version``
  reason ``intent_modified``. It returns the stored intent with its NEW etag.
* ``list`` pages one ``(customer_id, domain_id)`` partition, newest first, with an opaque cursor.
* ``list_in_states`` is the worker's cross-partition scan, oldest first, optionally only intents
  whose ``due_at`` has passed.
* Store outages raise ``dependency_transient`` (reason ``intent_store_unavailable``); a stored
  document that fails validation raises ``dependency_transient`` with ``upstream_invalid``. A
  failure is never reported as "not found" or as an empty page.

Only :class:`neurosphere_core.actions.service.ActionService` should call ``create``/``replace``.
"""

from __future__ import annotations

import base64
import binascii
import builtins
import itertools
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Final, Protocol, runtime_checkable

from neurosphere_core.actions.errors import (
    IDEMPOTENCY_KEY_REUSED,
    INTENT_MODIFIED,
    INTENT_STORE_UNAVAILABLE,
    ActionValidationError,
)
from neurosphere_core.actions.models import (
    CreateOutcome,
    IntentKey,
    StoredIntent,
    idempotency_lookup_id,
)
from neurosphere_core.audit.canonical import digests_equal
from neurosphere_core.errors import DependencyTransientError, StaleVersionError
from neurosphere_core.paging import Page
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "InMemoryIntentStore",
    "IntentStore",
    "check_limit",
    "decode_cursor",
    "encode_cursor",
    "idempotency_reused",
    "sort_key",
    "stale_intent",
    "store_unavailable",
]

_CURSOR_PREFIX: Final = "k1."


@runtime_checkable
class IntentStore(Protocol):
    async def create(self, stored: StoredIntent) -> CreateOutcome:
        """Store a new intent, or return the original for a replayed idempotency scope."""
        ...

    async def get(self, customer_id: str, domain_id: str, intent_id: str) -> StoredIntent | None:
        """Point read in one partition; ``None`` when absent."""
        ...

    async def find_by_idempotency_key(
        self, principal_id: str, idempotency_key: str, *, customer_id: str
    ) -> StoredIntent | None:
        """The intent stored under ``(principal_id, idempotency_key)``, if any."""
        ...

    async def replace(self, stored: StoredIntent, *, if_match: str) -> StoredIntent:
        """ETag-conditional replace; mismatch raises ``stale_version`` (``intent_modified``)."""
        ...

    async def list(
        self,
        customer_id: str,
        domain_id: str,
        *,
        state: str | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> Page[StoredIntent]:
        """One partition, newest first."""
        ...

    async def list_in_states(
        self,
        states: Sequence[str],
        *,
        due_before: datetime | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> builtins.list[StoredIntent]:
        """All partitions, oldest first; with ``due_before`` only intents with ``due_at <=`` it."""
        ...


# -- shared helpers -------------------------------------------------------------------------------


def sort_key(stored: StoredIntent) -> str:
    """Total order within a partition: creation instant, then id (fixed-width timestamps)."""
    return f"{stored.intent.created_at.root}#{stored.intent_id}"


def encode_cursor(key: str) -> str:
    return _CURSOR_PREFIX + base64.urlsafe_b64encode(key.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> str:
    """Inverse of :func:`encode_cursor`; anything else is ``invalid_schema`` ``invalid_cursor``."""
    if not cursor.startswith(_CURSOR_PREFIX):
        raise ActionValidationError("invalid_cursor", "cursor is not valid")
    try:
        return base64.urlsafe_b64decode(cursor[len(_CURSOR_PREFIX) :].encode("ascii")).decode(
            "utf-8"
        )
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise ActionValidationError("invalid_cursor", "cursor is not valid") from exc


def check_limit(limit: int) -> int:
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ActionValidationError("invalid_page_size", f"limit must be 1..{MAX_PAGE_SIZE}")
    return limit


def store_unavailable() -> DependencyTransientError:
    return DependencyTransientError("intent store unavailable", reason=INTENT_STORE_UNAVAILABLE)


def stale_intent() -> StaleVersionError:
    return StaleVersionError("intent was modified concurrently", reason=INTENT_MODIFIED)


def idempotency_reused() -> ActionValidationError:
    return ActionValidationError(
        IDEMPOTENCY_KEY_REUSED, "idempotency key was already used for a different request"
    )


# -- in-memory ------------------------------------------------------------------------------------


class InMemoryIntentStore:
    """Per-process store. Never a production store (no durability, no replication).

    Documents are kept in their serialized form and re-validated on every read, so the
    round-trip a durable store performs is exercised. ``fail_with`` makes every call raise
    (outage simulation).
    """

    def __init__(self) -> None:
        self._docs: dict[tuple[str, str, str], tuple[dict[str, Any], str]] = {}
        self._idempotency: dict[str, tuple[str, IntentKey]] = {}
        self._etags = itertools.count(1)
        self.error: Exception | None = None
        self.create_calls = 0
        self.replace_calls = 0

    def fail_with(self, error: Exception | None) -> None:
        self.error = error

    def _check(self) -> None:
        error = self.error
        if error is not None:
            raise error

    def _next_etag(self) -> str:
        return f'"{next(self._etags)}"'

    def _load(self, key: tuple[str, str, str]) -> StoredIntent | None:
        found = self._docs.get(key)
        if found is None:
            return None
        document, etag = found
        return StoredIntent.from_document(dict(document), etag=etag)

    def _put(self, stored: StoredIntent) -> StoredIntent:
        etag = self._next_etag()
        key = (stored.customer_id, stored.domain_id, stored.intent_id)
        self._docs[key] = (stored.to_document(), etag)
        loaded = self._load(key)
        assert loaded is not None
        return loaded

    async def create(self, stored: StoredIntent) -> CreateOutcome:
        self.create_calls += 1
        self._check()
        lookup = idempotency_lookup_id(stored.principal_id, stored.intent.idempotency_key)
        existing = self._idempotency.get(lookup)
        if existing is not None:
            digest, key = existing
            if not digests_equal(digest, stored.payload_digest):
                raise idempotency_reused()
            original = self._load((key.customer_id, key.domain_id, key.intent_id))
            if original is None:  # cannot happen in-process; mirrors the Cosmos repair path
                raise store_unavailable()
            return CreateOutcome(stored=original, created=False)
        self._idempotency[lookup] = (stored.payload_digest, stored.key)
        return CreateOutcome(stored=self._put(stored), created=True)

    async def get(self, customer_id: str, domain_id: str, intent_id: str) -> StoredIntent | None:
        self._check()
        return self._load((customer_id, domain_id, intent_id))

    async def find_by_idempotency_key(
        self, principal_id: str, idempotency_key: str, *, customer_id: str
    ) -> StoredIntent | None:
        self._check()
        found = self._idempotency.get(idempotency_lookup_id(principal_id, idempotency_key))
        if found is None or found[1].customer_id != customer_id:
            return None
        key = found[1]
        return self._load((key.customer_id, key.domain_id, key.intent_id))

    async def replace(self, stored: StoredIntent, *, if_match: str) -> StoredIntent:
        self.replace_calls += 1
        self._check()
        key = (stored.customer_id, stored.domain_id, stored.intent_id)
        current = self._docs.get(key)
        if current is None or current[1] != if_match:
            raise stale_intent()
        return self._put(stored)

    async def list(
        self,
        customer_id: str,
        domain_id: str,
        *,
        state: str | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> Page[StoredIntent]:
        self._check()
        check_limit(limit)
        after = decode_cursor(cursor) if cursor is not None else None
        rows: builtins.list[StoredIntent] = []
        for c, d, i in builtins.list(self._docs):
            if c != customer_id or d != domain_id:
                continue
            found = self._load((c, d, i))
            if found is not None and (state is None or found.state == state):
                rows.append(found)
        rows.sort(key=sort_key, reverse=True)
        if after is not None:
            rows = [s for s in rows if sort_key(s) < after]
        page = rows[:limit]
        next_cursor = encode_cursor(sort_key(page[-1])) if len(rows) > limit else None
        return Page[StoredIntent](items=tuple(page), next_cursor=next_cursor)

    async def list_in_states(
        self,
        states: Sequence[str],
        *,
        due_before: datetime | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> builtins.list[StoredIntent]:
        self._check()
        check_limit(limit)
        wanted = set(states)
        rows = [s for key in builtins.list(self._docs) if (s := self._load(key)) is not None]
        rows = [s for s in rows if s.state in wanted]
        if due_before is not None:
            rows = [s for s in rows if s.due_at is not None and s.due_at <= due_before]
        rows.sort(key=sort_key)
        return rows[:limit]
