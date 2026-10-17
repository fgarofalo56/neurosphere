"""Review queue for inference conflicts (PRP-10 clarification 8; consumed later by PRP-17).

When re-inference contradicts a steward lock or a curated reject, the catalog keeps the
curated state, still stores the observation, and emits a ``ReviewItem`` here. The HITL
workflow and UI are PRP-17; this module only defines the item, the queue protocol and an
in-memory implementation for tests and the sandbox.

Items are idempotent by ``id`` (derived from the edge, the conflict reason and the governing
curation decision), so replaying the same outbox batch never duplicates a review item.
Every method takes the server-derived ``IdentityScope`` first and only ever exposes items of
domains in that scope.
"""

from __future__ import annotations

from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from neurosphere_core.errors import ForbiddenError
from neurosphere_core.scope import IdentityScope

ConflictReason = Literal["conflicts_with_lock", "conflicts_with_reject"]
ReviewStatus = Literal["open", "resolved"]
ReviewResolution = Literal["kept_curation", "accepted_inference"]

_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:/=-]{0,255}$"
_CANON_PATTERN = r"^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+$"
_TS_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,9})?Z$"


class ReviewItem(BaseModel):
    """One inference-vs-curation conflict awaiting a steward decision."""

    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Field(pattern=_ID_PATTERN)]
    """Deterministic ID (see ``rules.review_item_id``); also usable as ``review_item_id``."""
    edge_id: Annotated[str, Field(pattern=_CANON_PATTERN, max_length=512)]
    relation_type: str
    cloud: Literal["commercial", "government"]
    customer_id: Annotated[str, Field(pattern=r"^[a-z0-9._-]{1,128}$")]
    domain_id: Annotated[str, Field(pattern=_CANON_PATTERN, max_length=512)]
    reason: ConflictReason
    governing_override_id: Annotated[str, Field(pattern=_CANON_PATTERN, max_length=512)] | None = (
        None
    )
    """The steward decision (lock or reject) the inference conflicts with."""
    observed_confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    presented_confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    new_evidence_ids: Annotated[list[str], Field(max_length=1000)]
    """Evidence of the conflicting observation (pointers, never payloads)."""
    created_at: Annotated[str, Field(pattern=_TS_PATTERN)]
    status: ReviewStatus = "open"
    resolved_at: Annotated[str, Field(pattern=_TS_PATTERN)] | None = None
    resolved_by: Annotated[str, Field(pattern=_CANON_PATTERN, max_length=512)] | None = None
    resolution: ReviewResolution | None = None


@runtime_checkable
class ReviewQueue(Protocol):
    """Scope-filtered queue of ``ReviewItem``. Out-of-scope items are invisible, not forbidden."""

    async def enqueue(self, scope: IdentityScope, item: ReviewItem) -> bool:
        """Add ``item``; return False when an item with the same ``id`` already exists.

        Raises ``ForbiddenError`` when the item's cloud, customer or domain is outside
        ``scope``.
        """
        ...

    async def get(self, scope: IdentityScope, item_id: str) -> ReviewItem | None:
        """The item, or None when it does not exist or is outside ``scope`` (same answer)."""
        ...

    async def list_open(self, scope: IdentityScope, limit: int = 100) -> tuple[ReviewItem, ...]:
        """Open items in scope, oldest first, at most ``limit`` (clamped to 1..500)."""
        ...

    async def resolve(
        self,
        scope: IdentityScope,
        item_id: str,
        *,
        resolved_by: str,
        resolution: ReviewResolution,
        resolved_at: str,
    ) -> ReviewItem:
        """Mark an item resolved. Raises ``ForbiddenError`` if missing or out of scope."""
        ...


def _visible(scope: IdentityScope, item: ReviewItem) -> bool:
    return (
        item.cloud == scope.cloud
        and item.customer_id == scope.customer_id
        and item.domain_id in scope.allowed_domains
    )


class InMemoryReviewQueue:
    """Process-local ``ReviewQueue`` (tests, sandbox). Not shared across processes."""

    def __init__(self) -> None:
        self._items: dict[str, ReviewItem] = {}

    async def enqueue(self, scope: IdentityScope, item: ReviewItem) -> bool:
        if not _visible(scope, item):
            raise ForbiddenError("review item is outside the caller's scope")
        if item.id in self._items:
            return False
        self._items[item.id] = item.model_copy(deep=True)
        return True

    async def get(self, scope: IdentityScope, item_id: str) -> ReviewItem | None:
        item = self._items.get(item_id)
        if item is None or not _visible(scope, item):
            return None
        return item.model_copy(deep=True)

    async def list_open(self, scope: IdentityScope, limit: int = 100) -> tuple[ReviewItem, ...]:
        bounded = max(1, min(limit, 500))
        found = sorted(
            (i for i in self._items.values() if i.status == "open" and _visible(scope, i)),
            key=lambda i: (i.created_at, i.id),
        )
        return tuple(i.model_copy(deep=True) for i in found[:bounded])

    async def resolve(
        self,
        scope: IdentityScope,
        item_id: str,
        *,
        resolved_by: str,
        resolution: ReviewResolution,
        resolved_at: str,
    ) -> ReviewItem:
        item = self._items.get(item_id)
        if item is None or not _visible(scope, item):
            raise ForbiddenError("review item not found in the caller's scope")
        updated = item.model_copy(
            update={
                "status": "resolved",
                "resolved_by": resolved_by,
                "resolution": resolution,
                "resolved_at": resolved_at,
            }
        )
        self._items[item_id] = updated
        return updated.model_copy(deep=True)
