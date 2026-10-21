"""HITL review item store port and the in-memory implementation (PRP-17 item 3, delta D7).

The port is shaped so a Cosmos implementation (OPEN follow-up, D7) maps onto documented
operations only: ``create`` is create-only (``create_item``), ``replace`` is an ETag-conditional
``replace_item`` (``if_match``; a mismatch is ``stale_version``), ``list`` is a parameterized
query on ``/customer_id`` + ``/domain_id`` with a continuation cursor, and ``due`` is a query
on the stored ``next_deadline`` field. There is no delete.

Every failure of the backing store surfaces as ``dependency_transient`` (reason
``hitl_store_unavailable``) so callers fail closed (503).
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Protocol, runtime_checkable

from neurosphere_core.errors import (
    DependencyTransientError,
    InvalidSchemaError,
    StaleVersionError,
)
from neurosphere_core.hitl.models import ReviewItem, format_timestamp
from neurosphere_core.paging import Page
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

__all__ = ["HitlStore", "InMemoryHitlStore", "decode_cursor", "encode_cursor"]


@runtime_checkable
class HitlStore(Protocol):
    async def create(self, item: ReviewItem) -> ReviewItem:
        """Insert ``item`` (create-only) and return it with its store ETag.

        An existing ``item_id`` is ``stale_version`` (reason ``review_item_exists``).
        """
        ...

    async def get(self, item_id: str) -> ReviewItem | None:
        """The item by id, or ``None``. Unscoped: the caller authorizes the item's domain."""
        ...

    async def replace(self, item: ReviewItem, *, if_match: str) -> ReviewItem:
        """Replace the stored item when its ETag equals ``if_match``; return it with a new ETag.

        Missing item or ETag mismatch is ``stale_version`` (reason ``etag_mismatch``).
        """
        ...

    async def list(
        self,
        scope: IdentityScope,
        domain: str,
        *,
        kind: str | None = None,
        state: str | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> Page[ReviewItem]:
        """Items of ``domain`` in the caller's scope, oldest first (``created_at``, ``item_id``).

        A domain outside the scope yields an empty page; an invalid cursor or limit is
        ``invalid_schema``.
        """
        ...

    async def due(self, now: datetime, limit: int = 100) -> list[ReviewItem]:
        """Non-final items whose earliest active stored deadline is ``<= now``, earliest first."""
        ...


def encode_cursor(item: ReviewItem) -> str:
    raw = json.dumps([format_timestamp(item.created_at), item.item_id])
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        decoded = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
    except (binascii.Error, UnicodeError, ValueError):
        raise InvalidSchemaError("invalid cursor", reason="invalid_cursor") from None
    if (
        not isinstance(decoded, list)
        or len(decoded) != 2  # pyright: ignore[reportUnknownArgumentType]
        or not all(isinstance(part, str) for part in decoded)  # pyright: ignore[reportUnknownVariableType]
    ):
        raise InvalidSchemaError("invalid cursor", reason="invalid_cursor")
    return str(decoded[0]), str(decoded[1])  # pyright: ignore[reportUnknownArgumentType]


def _sort_key(item: ReviewItem) -> tuple[str, str]:
    return format_timestamp(item.created_at), item.item_id


def _visible(scope: IdentityScope, domain: str, item: ReviewItem) -> bool:
    return (
        item.cloud == scope.cloud
        and item.customer_id == scope.customer_id
        and domain in scope.allowed_domains
        and item.domain_id == domain
    )


def _new_etag() -> str:
    return f'"{uuid.uuid4()}"'


class InMemoryHitlStore:
    """Process-local store (tests, sandbox). Shared across workers in one process by reference.

    ``outage = True`` makes every call raise ``dependency_transient``, standing in for a store
    outage. ``replace_count`` counts successful replaces (tests assert on it).
    """

    def __init__(self, *, etag_factory: Callable[[], str] = _new_etag) -> None:
        self._items: dict[str, str] = {}
        self._etags = etag_factory
        self.outage = False
        self.replace_count = 0

    def _check(self) -> None:
        if self.outage:
            raise DependencyTransientError(
                "review store unavailable", reason="hitl_store_unavailable"
            )

    def _load(self, item_id: str) -> ReviewItem | None:
        raw = self._items.get(item_id)
        return None if raw is None else ReviewItem.model_validate_json(raw)

    def _save(self, item: ReviewItem) -> ReviewItem:
        stored = item.model_copy(update={"etag": self._etags()})
        self._items[item.item_id] = stored.model_dump_json()
        return stored

    async def create(self, item: ReviewItem) -> ReviewItem:
        self._check()
        if item.item_id in self._items:
            raise StaleVersionError("review item already exists", reason="review_item_exists")
        return self._save(item)

    async def get(self, item_id: str) -> ReviewItem | None:
        self._check()
        return self._load(item_id)

    async def replace(self, item: ReviewItem, *, if_match: str) -> ReviewItem:
        self._check()
        current = self._load(item.item_id)
        if current is None or current.etag != if_match:
            raise StaleVersionError("review item changed since it was read", reason="etag_mismatch")
        self.replace_count += 1
        return self._save(item)

    async def list(
        self,
        scope: IdentityScope,
        domain: str,
        *,
        kind: str | None = None,
        state: str | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> Page[ReviewItem]:
        self._check()
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise InvalidSchemaError(f"limit must be 1..{MAX_PAGE_SIZE}", reason="invalid_limit")
        after = decode_cursor(cursor) if cursor else None
        rows = sorted(
            (
                item
                for item in (self._load(key) for key in self._items)
                if item is not None
                and _visible(scope, domain, item)
                and (kind is None or item.kind == kind)
                and (state is None or item.state_name == state)
                and (after is None or _sort_key(item) > after)
            ),
            key=_sort_key,
        )
        page = rows[:limit]
        next_cursor = encode_cursor(page[-1]) if len(rows) > limit else None
        return Page[ReviewItem](items=tuple(page), next_cursor=next_cursor)

    async def due(self, now: datetime, limit: int = 100) -> list[ReviewItem]:
        self._check()
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise InvalidSchemaError(f"limit must be 1..{MAX_PAGE_SIZE}", reason="invalid_limit")
        found: list[tuple[datetime, str, ReviewItem]] = []
        for key in self._items:
            item = self._load(key)
            if item is None:
                continue
            deadline = item.next_deadline()
            if deadline is not None and deadline <= now:
                found.append((deadline, item.item_id, item))
        found.sort(key=lambda row: (row[0], row[1]))
        return [row[2] for row in found[:limit]]
