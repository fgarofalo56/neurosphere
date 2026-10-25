"""``ReviewRouter`` backed by the HITL review queue (PRP-29 item 3; replaces the in-memory stub).

Routing a recommendation opens ONE ``recommendation`` review item through
:meth:`HitlService.open_item` (audited, deadlines from the review policy, never a raw store
write). It is idempotent per ``(customer, recommendation)``: the item is found by its
``subject_ref`` (the recommendation id) among the domain's ``recommendation`` items, oldest
first, so a second call returns the same review request. ``review_request_id`` is the HITL item id.

Concurrency: the find-then-open runs under one in-process lock, so concurrent calls in one
worker cannot open two items. Two processes racing can, in theory, each open one; the lookup then
always returns the oldest (``created_at``, ``item_id``), so every later call converges on the same
request and the other item is never surfaced as "the" review request.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from neurosphere_contracts.actions.v1.actor import Actor
from neurosphere_core.errors import DependencyTransientError, ForbiddenError
from neurosphere_core.hitl import HitlService, ReviewItem
from neurosphere_core.paging.models import MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

from neurosphere_api.recommendations.review import ReviewRequest

__all__ = ["HitlReviewRouter"]

#: The scan stops (fail closed) rather than walk an unbounded queue.
_MAX_SCAN_PAGES = 20


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _correlation_id() -> str:
    return f"review-route-{uuid.uuid4().hex}"


def _actor(scope: IdentityScope) -> Actor:
    principal = scope.to_contract().principal
    return Actor.model_validate(
        {
            "principal_pseudonym": principal.principal_pseudonym,
            "principal_kind": principal.principal_kind,
            "on_behalf_of": None,
        }
    )


class HitlReviewRouter:
    """:class:`ReviewRouter` over a :class:`HitlService`."""

    def __init__(
        self,
        service: HitlService,
        *,
        clock: Callable[[], datetime] = _utc_now,
        correlation_id: Callable[[], str] = _correlation_id,
    ) -> None:
        self._service = service
        self._clock = clock
        self._correlation_id = correlation_id
        self._lock = asyncio.Lock()

    async def route(
        self, scope: IdentityScope, domain: str, recommendation_id: str
    ) -> ReviewRequest:
        self._require_domain(scope, domain)
        async with self._lock:
            existing = await self._find(scope, domain, recommendation_id)
            if existing is not None:
                return ReviewRequest(review_request_id=existing.item_id)
            item = await self._service.open_item(
                kind="recommendation",
                customer_id=scope.customer_id,
                domain_id=domain,
                subject_ref=recommendation_id,
                now=self._clock(),
                correlation_id=self._correlation_id(),
                opened_by=_actor(scope),
                scope_hash=scope.scope_hash,
                channel="rest",
            )
        return ReviewRequest(review_request_id=item.item_id)

    async def status(
        self, scope: IdentityScope, domain: str, recommendation_id: str
    ) -> ReviewRequest | None:
        existing = await self._find(scope, domain, recommendation_id)
        return None if existing is None else ReviewRequest(review_request_id=existing.item_id)

    @staticmethod
    def _require_domain(scope: IdentityScope, domain: str) -> None:
        if domain not in scope.allowed_domains:
            raise ForbiddenError("domain is outside the caller's scope")

    async def _find(
        self, scope: IdentityScope, domain: str, recommendation_id: str
    ) -> ReviewItem | None:
        cursor: str | None = None
        for _ in range(_MAX_SCAN_PAGES):
            page = await self._service.store.list(
                scope, domain, kind="recommendation", cursor=cursor, limit=MAX_PAGE_SIZE
            )
            for item in page.items:
                if item.subject_ref == recommendation_id:
                    return item
            if page.next_cursor is None:
                return None
            cursor = page.next_cursor
        raise DependencyTransientError(
            "review queue too large to look up the recommendation", reason="review_scan_exceeded"
        )
