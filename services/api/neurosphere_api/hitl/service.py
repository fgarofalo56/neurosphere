"""Review queue flows: scope-filtered list, read, assignment, decisions (PRP-17 item 4).

Visibility is per kind, on top of the route's ``data.read`` on the path domain: ``maker_checker``
items need ``action.approve`` on the domain, insight kinds (``relationship``,
``evaluation_dispute``, ``recommendation``, ``policy_exception``) need ``catalog.curate``. The
check uses the server-derived ``IdentityScope``; ``HitlService`` then rechecks the reviewer
against the current policy store before any assignment or decision.

A ``maker_checker`` decision is delegated to
:func:`neurosphere_api.actions.approval.decide_maker_checker`, the same function the action
route uses (one approval path). Insight decisions only record the review outcome; they never
touch an action.

A list page is filtered after the store read, so a page can hold fewer than ``limit`` items
(even none) while ``next_cursor`` is still set; clients follow the cursor until it is ``null``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Final

from neurosphere_core.actions import ActionCaller, IntentKey
from neurosphere_core.auth.scope import Permission, permits
from neurosphere_core.errors import CapabilityUnavailableError, ForbiddenError
from neurosphere_core.hitl import INSIGHT_KINDS, ReviewItem
from neurosphere_core.scope import IdentityScope

from neurosphere_api.actions.approval import decide_maker_checker
from neurosphere_api.actions.common import caller_for, load_intent, not_found
from neurosphere_api.actions.dependencies import ActionPlane
from neurosphere_api.hitl.models import (
    AssignmentBody,
    ReviewDecisionBody,
    ReviewItemList,
    ReviewItemView,
)
from neurosphere_api.hitl.ports import ReviewerDirectory

__all__ = ["ReviewQueueApi", "permission_for_kind"]

_MAKER_CHECKER: Final = "maker_checker"


def permission_for_kind(kind: str) -> Permission:
    return Permission.ACTION_APPROVE if kind == _MAKER_CHECKER else Permission.CATALOG_CURATE


class ReviewQueueApi:
    def __init__(self, plane: ActionPlane, scope: IdentityScope, authz_now: datetime) -> None:
        self._plane = plane
        self._scope = scope
        self._now = authz_now

    # -- visibility ------------------------------------------------------------------------

    def _may_review(self, kind: str, domain: str) -> bool:
        return (
            permits(self._scope, permission_for_kind(kind), now=self._now, domain_id=domain) is True
        )

    def _visible_kinds(self, domain: str) -> frozenset[str]:
        kinds: set[str] = set()
        if self._may_review(_MAKER_CHECKER, domain):
            kinds.add(_MAKER_CHECKER)
        if self._may_review("relationship", domain):
            kinds.update(INSIGHT_KINDS)
        return frozenset(kinds)

    def _in_scope(self, item: ReviewItem, domain: str) -> bool:
        return (
            item.domain_id == domain
            and item.customer_id == self._scope.customer_id
            and item.cloud == self._scope.cloud
        )

    async def _load(self, domain: str, item_id: str) -> ReviewItem:
        """The item in ``domain`` and visible to the caller, else 404 (or 403 for its kind)."""
        item = await self._plane.hitl.get(item_id)
        if item is None or not self._in_scope(item, domain):
            raise not_found()
        if not self._may_review(item.kind, domain):
            raise ForbiddenError(
                "insufficient scope for this review item", reason="permission_missing"
            )
        return item

    async def _view(self, item: ReviewItem) -> ReviewItemView:
        return ReviewItemView.build(item, await self._plane.hitl.decisions(item.item_id))

    async def _views(self, items: Iterable[ReviewItem]) -> list[ReviewItemView]:
        return [await self._view(item) for item in items]

    # -- reads -----------------------------------------------------------------------------

    async def list(
        self,
        domain: str,
        *,
        kind: str | None,
        state: str | None,
        cursor: str | None,
        limit: int,
    ) -> ReviewItemList:
        visible = self._visible_kinds(domain)
        if not visible or (kind is not None and kind not in visible):
            return ReviewItemList(items=[], next_cursor=None)
        store_kind = kind
        if store_kind is None and visible == {_MAKER_CHECKER}:
            store_kind = _MAKER_CHECKER
        page = await self._plane.hitl.store.list(
            self._scope, domain, kind=store_kind, state=state, cursor=cursor, limit=limit
        )
        rows = [item for item in page.items if item.kind in visible]
        return ReviewItemList(items=await self._views(rows), next_cursor=page.next_cursor)

    async def get(self, domain: str, item_id: str) -> ReviewItemView:
        return await self._view(await self._load(domain, item_id))

    # -- writes ----------------------------------------------------------------------------

    def _caller(self, correlation_id: str) -> ActionCaller:
        return caller_for(self._scope, correlation_id, "rest")

    async def assign(
        self, domain: str, item_id: str, body: AssignmentBody, correlation_id: str
    ) -> ReviewItemView:
        item = await self._load(domain, item_id)
        caller = self._caller(correlation_id)
        assignee_id = body.assignee_principal_id
        assignee = None
        if assignee_id is not None and assignee_id != caller.principal_id:
            directory = self._plane.reviewer_directory
            if not isinstance(directory, ReviewerDirectory):
                raise CapabilityUnavailableError(
                    "reviewer_directory_unconfigured",
                    "assigning another reviewer is not available; claim the item instead",
                )
            assignee = await directory.actor_for(item.customer_id, assignee_id)
            if assignee is None:
                raise ForbiddenError(
                    "principal may not review this item", reason="reviewer_not_authorized"
                )
        else:
            assignee_id = None
        updated = await self._plane.hitl.assign(
            item.item_id,
            assignee_id,
            caller.principal_id,
            self._plane.now(),
            by=caller.actor,
            scope_hash=caller.scope_hash,
            correlation_id=caller.correlation_id,
            assignee=assignee,
            channel=caller.channel,
        )
        return await self._view(updated)

    async def decide(
        self, domain: str, item_id: str, body: ReviewDecisionBody, correlation_id: str
    ) -> ReviewItemView:
        item = await self._load(domain, item_id)
        plane = self._plane
        if item.kind == _MAKER_CHECKER:
            if item.intent_id is None:  # cannot happen: ReviewItem validates it
                raise not_found()
            stored = await load_intent(
                plane, IntentKey(item.customer_id, item.domain_id, item.intent_id)
            )
            caller = caller_for(self._scope, correlation_id, stored.intent.channel)
            await decide_maker_checker(
                plane,
                stored=stored,
                item=item,
                caller=caller,
                decision=body.decision,
                reason=body.reason,
                confirmation_hash=body.confirmation_hash,
            )
        else:
            caller = self._caller(correlation_id)
            await plane.hitl.decide(
                item.item_id,
                caller.principal_id,
                caller.actor,
                body.decision,
                body.reason,
                body.confirmation_hash,
                plane.now(),
                caller.correlation_id,
                scope_hash=caller.scope_hash,
                channel=caller.channel,
            )
        latest = await plane.hitl.get(item.item_id)
        if latest is None:
            raise not_found()
        return await self._view(latest)
