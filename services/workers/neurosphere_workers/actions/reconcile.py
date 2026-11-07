"""Review-reconcile sweep: close maker-checker review items the action plane left behind.

PRP-17 audit close-out. Two gaps leave a ``maker_checker`` review item open although its action
can no longer use it:

1. The completion hook (:class:`~neurosphere_workers.actions.completion.ReviewItemCompletion`)
   only fires inside ``ActionExecutor.execute``, and the executor worker only lists
   ``executing`` intents. A hook failure, or an intent that ends OUTSIDE the executor
   (``ActionService.expire_due``, a confirmation expiring at approval), leaves the item
   ``approved`` or still undecided.
2. ``HitlService.open_item`` succeeded but ``ActionService.link_review_item`` then failed: an
   orphan item exists that no decision can reach (the approval path refuses an item the intent
   does not link, ``review_item_mismatch``).

Design (the smallest correct one): drive the sweep from the HITL side. The set of open
``maker_checker`` items is small and shrinks as the sweep closes them, whereas terminal intents
accumulate forever, so ``HitlStore.open_maker_checker`` (ids only, oldest first, cross-partition,
bounded) is the scan and each item is then loaded and paired with its intent, read from the
ITEM's own ``(customer_id, domain_id)`` partition (a pairing can never cross customers).

Per item (``linked`` = the intent's ``review_item_id`` names this item):

* linked, intent terminal, item ``approved`` -> ``mark_executed`` (``succeeded``) or
  ``mark_failed`` (``failed``/``rolled_back``/``expired``): the same completion the hook runs.
* linked, intent terminal, item undecided -> ``mark_expired`` (no decision can apply any more).
* orphan younger than ``orphan_grace`` -> skipped (the API's open-then-link may be in flight).
* orphan, intent ``awaiting_approval`` and linking NO item -> re-link it
  (``link_review_item(only_if_unlinked=True)``): this repairs exactly the failed link write and
  keeps the reviewer queue intact. A link written meanwhile wins; the item then becomes a
  duplicate and the next pass closes it.
* any other undecided orphan (intent missing, terminal, or linking another item) ->
  ``mark_expired``.
* an ``approved`` orphan whose intent is missing or terminal -> ``mark_failed``; one whose intent
  is still live is left alone and logged (no safe automatic answer).
* anything else is a no-op (a live intent with its own linked item is normal).

Guarantees:

* Idempotent and restart-safe: every write is an ETag-conditional transition out of an open
  state, and closed items drop out of the scan, so a second pass changes nothing. The scan
  position is the runner checkpoint; a restart at worst rescans.
* Audited: each reconcile action writes an ``ActionAuditEvent`` (operation
  ``hitl.review.reconcile``) ``before`` the change - if that write fails the item is skipped, fail
  closed - and an ``after`` record once it is done; the HITL transitions additionally audit
  themselves on the review chain.
* Fail closed: a store outage while scanning is an idle tick; a failure on one item (outage,
  malformed document, ETag race) skips that item until the next pass. Nothing escapes the loop.
* Bounded: one batch is at most ``batch_limit`` items; a complete pass starts again only after
  ``pass_interval``.
* It never touches a target system: no connector, registry or ``apply``/``rollback`` here
  (``ActionExecutor`` stays the single write path).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal

from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_core.actions import (
    TERMINAL_STATES,
    ActionAuditEvent,
    ActionAuditor,
    ActionService,
    IntentKey,
    IntentNotFoundError,
    StoredIntent,
)
from neurosphere_core.errors import NeuroSphereError
from neurosphere_core.hitl import (
    DECIDABLE_STATES,
    SYSTEM_ACTOR,
    SYSTEM_SCOPE_HASH,
    HitlService,
    ReviewItem,
    ReviewItemRef,
)

from neurosphere_workers.runtime import Batch, BatchOutcome, Worker

__all__ = [
    "DEFAULT_ORPHAN_GRACE",
    "DEFAULT_PASS_INTERVAL",
    "DEFAULT_RECONCILE_BATCH_LIMIT",
    "RECONCILE_OPERATION",
    "ReconcileOutcome",
    "ReconcileReport",
    "ReviewReconcileWorker",
]

logger = logging.getLogger("neurosphere.workers.actions.reconcile")

DEFAULT_RECONCILE_BATCH_LIMIT: Final = 50
DEFAULT_PASS_INTERVAL: Final = timedelta(minutes=1)
DEFAULT_ORPHAN_GRACE: Final = timedelta(minutes=5)
RECONCILE_OPERATION: Final = "hitl.review.reconcile"

ReconcileOutcome = Literal[
    "executed",  # linked item marked executed
    "failed",  # item marked failed
    "expired",  # undecided item closed
    "relinked",  # orphan linked to its unlinked intent
    "noop",  # nothing to do
    "grace",  # orphan too young to judge
    "conflict",  # changed concurrently; the next pass sees the new state
    "error",  # outage, malformed document, audit failure: skipped until the next pass
]
_Action = Literal["mark_executed", "mark_failed", "mark_expired", "relink"]
_RESULT: Final[dict[_Action, ReconcileOutcome]] = {
    "mark_executed": "executed",
    "mark_failed": "failed",
    "mark_expired": "expired",
    "relink": "relinked",
}
_TARGET_STATE: Final[dict[_Action, str | None]] = {
    "mark_executed": "executed",
    "mark_failed": "failed",
    "mark_expired": "expired",
    "relink": None,
}

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ReconcileReport:
    """One batch: the outcome per scanned item id, in scan order."""

    at: datetime
    outcomes: tuple[tuple[str, ReconcileOutcome], ...] = ()
    scan_failed: bool = False

    def count(self, outcome: ReconcileOutcome) -> int:
        return sum(1 for _, found in self.outcomes if found == outcome)

    @property
    def changed(self) -> int:
        return sum(self.count(o) for o in ("executed", "failed", "expired", "relinked"))


@dataclass(frozen=True)
class _Plan:
    action: _Action
    why: str


@dataclass
class _Cursor:
    after: str | None = None
    pass_started_at: datetime | None = None


class ReviewReconcileWorker(Worker):
    """Polls open ``maker_checker`` review items and closes or re-links the stale ones.

    A PRP-05 :class:`~neurosphere_workers.runtime.Worker`: run it under ``WorkerRunner`` (the
    checkpoint is the scan position, ``""`` once a pass is complete) or call :meth:`run_once`.
    ``customer_id`` restricts the sweep to one customer (a per-tenant deployment).
    """

    partition_key = "action-review-reconcile"

    def __init__(
        self,
        hitl: HitlService,
        actions: ActionService,
        *,
        auditor: ActionAuditor,
        batch_limit: int = DEFAULT_RECONCILE_BATCH_LIMIT,
        pass_interval: timedelta = DEFAULT_PASS_INTERVAL,
        orphan_grace: timedelta = DEFAULT_ORPHAN_GRACE,
        customer_id: str | None = None,
        clock: Clock = _utc_now,
    ) -> None:
        if batch_limit < 1:
            raise ValueError("batch_limit must be >= 1")
        self._hitl = hitl
        self._actions = actions
        self._auditor = auditor
        self._limit = batch_limit
        self._interval = pass_interval
        self._grace = orphan_grace
        self._customer = customer_id
        self._clock = clock
        self._cursor = _Cursor()
        self._scan_failed = False
        self.last_report: ReconcileReport | None = None

    # -- runner surface ----------------------------------------------------------------------

    async def fetch_batch(self, checkpoint: str | None) -> Batch | None:
        return await self._fetch(checkpoint or None, gated=True)

    async def process_batch(self, batch: Batch) -> BatchOutcome:
        now = self._clock()
        outcomes: list[tuple[str, ReconcileOutcome]] = []
        for item_id in batch.items:
            if isinstance(item_id, str):
                outcomes.append((item_id, await self._reconcile_safely(item_id, now)))
        self._cursor.after = batch.checkpoint or None
        self.last_report = ReconcileReport(at=now, outcomes=tuple(outcomes))
        return BatchOutcome.ACCEPTED

    async def run_once(self) -> ReconcileReport:
        """One batch from the current scan position, ignoring ``pass_interval`` (tests, CLIs)."""
        now = self._clock()
        batch = await self._fetch(self._cursor.after, gated=False)
        if batch is None:
            report = ReconcileReport(at=now, scan_failed=self._scan_failed)
            self.last_report = report
            return report
        await self.process_batch(batch)
        return self.last_report or ReconcileReport(at=now)

    # -- scan --------------------------------------------------------------------------------

    async def _fetch(self, after: str | None, *, gated: bool) -> Batch | None:
        now = self._clock()
        self._scan_failed = False
        if after is None:
            started = self._cursor.pass_started_at
            if gated and started is not None and now < started + self._interval:
                return None
            self._cursor.pass_started_at = now
        try:
            refs: list[ReviewItemRef] = await self._hitl.store.open_maker_checker(
                after=after, customer_id=self._customer, limit=self._limit
            )
        except Exception as exc:
            # Fail closed: an outage is an idle tick; the position is kept for the retry.
            self._scan_failed = True
            logger.warning(
                "review reconcile scan failed; retrying next tick",
                extra={"event": "action.reconcile_scan_failed", "reason": _reason(exc)},
            )
            return None
        if not refs:
            if after is None:
                return None
            return Batch(items=(), checkpoint="")  # pass complete: commit the wrap
        checkpoint = refs[-1].position if len(refs) >= self._limit else ""
        return Batch(items=tuple(ref.item_id for ref in refs), checkpoint=checkpoint)

    # -- one item ----------------------------------------------------------------------------

    async def _reconcile_safely(self, item_id: str, now: datetime) -> ReconcileOutcome:
        try:
            return await self._reconcile(item_id, now)
        except Exception as exc:
            logger.warning(
                "review reconcile skipped an item; retrying next pass",
                extra={
                    "event": "action.reconcile_item_failed",
                    "review_item_id": item_id,
                    "reason": _reason(exc),
                },
            )
            return "error"

    async def _reconcile(self, item_id: str, now: datetime) -> ReconcileOutcome:
        item = await self._hitl.get(item_id)
        if item is None or item.kind != "maker_checker" or item.intent_id is None:
            return "noop"
        if self._customer is not None and item.customer_id != self._customer:
            return "noop"
        intent = await self._intent_of(item)
        linked = intent is not None and intent.review_item_id == item.item_id
        if not linked and now - item.created_at < self._grace:
            return "grace"
        plan = self._plan(item, intent, linked=linked)
        if plan is None:
            return "noop"
        return await self._apply(item, intent, plan, now)

    async def _intent_of(self, item: ReviewItem) -> StoredIntent | None:
        assert item.intent_id is not None
        key = IntentKey(item.customer_id, item.domain_id, item.intent_id)
        try:
            return await self._actions.get(key)
        except IntentNotFoundError:
            return None

    @staticmethod
    def _plan(item: ReviewItem, intent: StoredIntent | None, *, linked: bool) -> _Plan | None:
        state = item.state_name
        undecided = state in DECIDABLE_STATES
        terminal = intent is not None and intent.state in TERMINAL_STATES
        if linked:
            assert intent is not None
            if not terminal:
                return None
            if state == "approved":
                if intent.state == "succeeded":
                    return _Plan("mark_executed", "intent_succeeded")
                return _Plan("mark_failed", f"intent_{intent.state}")
            if undecided:
                return _Plan("mark_expired", f"intent_{intent.state}")
            return None
        # Orphan: no decision can reach this item through the one approval path.
        if undecided:
            if (
                intent is not None
                and intent.state == "awaiting_approval"
                and intent.review_item_id is None
            ):
                return _Plan("relink", "orphan_unlinked_intent")
            if intent is None:
                return _Plan("mark_expired", "orphan_intent_missing")
            return _Plan("mark_expired", "orphan_duplicate" if not terminal else "orphan_ended")
        if state == "approved":
            if intent is None or terminal:
                return _Plan("mark_failed", "orphan_approved")
            logger.warning(
                "approved orphan review item with a live intent left for an operator",
                extra={"event": "action.reconcile_orphan_approved", "review_item_id": item.item_id},
            )
        return None

    async def _apply(
        self, item: ReviewItem, intent: StoredIntent | None, plan: _Plan, now: datetime
    ) -> ReconcileOutcome:
        correlation_id = f"reconcile-{item.item_id[:8]}"
        before = self._event(item, intent, plan, kind="before", correlation_id=correlation_id)
        try:
            await self._auditor.record(before)  # fail closed: no audit, no change
        except Exception as exc:
            logger.warning(
                "review reconcile audit failed; item skipped",
                extra={"event": "action.reconcile_audit_failed", "reason": _reason(exc)},
            )
            return "error"
        try:
            await self._perform(item, plan, now, correlation_id)
        except NeuroSphereError as exc:
            await self._record_after(item, intent, plan, correlation_id, failed=_reason(exc))
            if exc.code == "stale_version" or exc.reason == "review_link_not_allowed":
                return "conflict"
            return "error"
        await self._record_after(item, intent, plan, correlation_id, failed=None)
        return _RESULT[plan.action]

    async def _perform(
        self, item: ReviewItem, plan: _Plan, now: datetime, correlation: str
    ) -> None:
        if plan.action == "mark_executed":
            await self._hitl.mark_executed(item.item_id, now, correlation_id=correlation)
        elif plan.action == "mark_failed":
            await self._hitl.mark_failed(item.item_id, now, correlation_id=correlation)
        elif plan.action == "mark_expired":
            await self._hitl.mark_expired(item.item_id, now, correlation_id=correlation)
        else:
            assert item.intent_id is not None
            await self._actions.link_review_item(
                IntentKey(item.customer_id, item.domain_id, item.intent_id),
                item.item_id,
                only_if_unlinked=True,
            )

    async def _record_after(
        self,
        item: ReviewItem,
        intent: StoredIntent | None,
        plan: _Plan,
        correlation_id: str,
        *,
        failed: str | None,
    ) -> None:
        event = self._event(
            item, intent, plan, kind="after", correlation_id=correlation_id, failed=failed
        )
        try:
            await self._auditor.record(event)
        except Exception as exc:  # the change (if any) is already audited on the review chain
            logger.warning(
                "review reconcile after-audit failed",
                extra={"event": "action.reconcile_audit_failed", "reason": _reason(exc)},
            )

    def _event(
        self,
        item: ReviewItem,
        intent: StoredIntent | None,
        plan: _Plan,
        *,
        kind: Literal["before", "after"],
        correlation_id: str,
        failed: str | None = None,
    ) -> ActionAuditEvent:
        if intent is not None:
            target, version = intent.intent.target, intent.intent.target_version
        else:
            target = TargetRef(canonical_id=item.subject_ref, entity_type="review_item")
            version = None
        return ActionAuditEvent(
            kind=kind,
            operation=RECONCILE_OPERATION,
            actor=SYSTEM_ACTOR,
            scope_hash=SYSTEM_SCOPE_HASH,
            correlation_id=correlation_id,
            channel="worker",
            customer_id=item.customer_id,
            domain_id=item.domain_id,
            intent_id=item.intent_id,
            target=target,
            target_version=version,
            from_state=item.state_name,
            to_state=_TARGET_STATE[plan.action],
            result=None if kind == "before" else ("failed" if failed else "succeeded"),
            reason=(failed or f"{plan.action}.{plan.why}")[:64],
        )


def _reason(exc: BaseException) -> str:
    if isinstance(exc, NeuroSphereError) and isinstance(exc.reason, str) and exc.reason:
        return exc.reason[:64]
    return type(exc).__name__
