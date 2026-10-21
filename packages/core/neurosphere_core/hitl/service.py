"""HITL service: open, assign, decide, record the action outcome, apply timers (PRP-17 item 3).

This service records review state and decisions only. It never executes or transitions an
action: on a ``maker_checker`` approval, item 4 calls the action service itself and reports the
outcome back through :meth:`HitlService.mark_executed` / :meth:`HitlService.mark_failed`.

Rules enforced on every assignment and decision (each refusal is audited as ``denied``):

* Reviewer authorization through :class:`ReviewerAuthorizer` with the policy's permission
  (``action.approve`` for maker-checker, ``catalog.curate`` for insight kinds). Denial is
  ``forbidden`` (``reviewer_not_authorized``); a policy outage propagates as
  ``dependency_transient`` (fail closed, 503).
* Self-approval: when the policy forbids it, a reviewer whose REAL principal id equals the
  maker's (or the principal the maker acted on behalf of) is refused with ``forbidden``
  (``self_approval_forbidden``). Pseudonyms, display names and sessions are never compared.
* Maker-checker decisions must carry the item's exact ``confirmation_hash`` (else
  ``invalid_schema``, reason ``confirmation_hash_mismatch``; the taxonomy has no
  ``validation_error`` code). Insight decisions must not carry one.
* Decided items are final: another decision is ``stale_version`` (``review_item_final``).
* An assigned item can only be decided by its assignee (``review_item_assigned_to_other``).

Write order for a decision: the decision is appended to the audit-backed :class:`DecisionLog`
first (fail closed: no audit, no decision), then the item is replaced under its ETag. If the
replace loses a race, the caller gets ``stale_version`` and the winning decision is the one the
item's ``decision_id`` names; the loser's record stays in the append-only log as history.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Literal

from neurosphere_contracts.actions.v1.actor import Actor
from pydantic import BaseModel, ConfigDict, ValidationError

from neurosphere_core.audit import (
    AuditContext,
    AuditDraft,
    AuditRepository,
    build_after,
    build_before,
    build_denied,
    digests_equal,
    run_audited_mutation,
)
from neurosphere_core.audit.builders import Channel
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    NeuroSphereError,
    StaleVersionError,
)
from neurosphere_core.hitl.auditing import (
    SYSTEM_ACTOR,
    SYSTEM_SCOPE_HASH,
    audit_chain_for,
    audit_context,
    item_subject,
    refusal_code,
)
from neurosphere_core.hitl.authz import ReviewerAuthorizer
from neurosphere_core.hitl.decisions import DecisionLog, ImmutableDecision
from neurosphere_core.hitl.models import (
    DECIDABLE_STATES,
    ReviewItem,
    ReviewKind,
    format_timestamp,
    transition,
)
from neurosphere_core.hitl.notify import Notification, NotificationEvent, Notifier
from neurosphere_core.hitl.policy import ReviewPolicy, ReviewPolicyRegistry
from neurosphere_core.hitl.store import HitlStore
from neurosphere_core.hitl.timers import TimerAction, apply_timer_action, evaluate_timers

__all__ = ["DECISION_SCHEMA_VERSION", "HitlService", "TimerOutcome"]

logger = logging.getLogger("neurosphere.core.hitl")

DECISION_SCHEMA_VERSION = "1.0.0"

IdFactory = Callable[[], str]
_ASSIGNABLE = frozenset({"pending", "assigned", "escalated"})
_UNASSIGNED = {
    "assignee_principal_id": None,
    "assignee": None,
    "assigned_at": None,
    "assignment_due_at": None,
}


def _uuid4() -> str:
    return str(uuid.uuid4())


class TimerOutcome(BaseModel):
    """Result of one timer pass over one item."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    item: ReviewItem
    """The stored item after this pass (unchanged when nothing applied or the race was lost)."""
    applied: tuple[TimerAction, ...] = ()
    conflict: bool = False
    """True when another worker changed the item first (ETag mismatch); nothing was applied."""
    notifications_failed: int = 0


class HitlService:
    def __init__(
        self,
        store: HitlStore,
        decisions: DecisionLog,
        audit: AuditRepository,
        policies: ReviewPolicyRegistry,
        authorizer: ReviewerAuthorizer,
        *,
        notifiers: Sequence[Notifier] = (),
        id_factory: IdFactory = _uuid4,
    ) -> None:
        self._store = store
        self._decisions = decisions
        self._audit = audit
        self._policies = policies
        self._authorizer = authorizer
        self._notifiers = tuple(notifiers)
        self._ids = id_factory

    @property
    def store(self) -> HitlStore:
        return self._store

    def policy_for(self, item: ReviewItem) -> ReviewPolicy:
        return self._policies.resolve(item.kind, item.action_kind)

    # -- open ------------------------------------------------------------------------------

    async def open_item(
        self,
        *,
        kind: ReviewKind,
        customer_id: str,
        domain_id: str,
        subject_ref: str,
        now: datetime,
        correlation_id: str,
        action_kind: str | None = None,
        intent_id: str | None = None,
        confirmation_hash: str | None = None,
        maker_principal_id: str | None = None,
        maker_on_behalf_of_principal_id: str | None = None,
        maker: Actor | None = None,
        opened_by: Actor = SYSTEM_ACTOR,
        scope_hash: str = SYSTEM_SCOPE_HASH,
        channel: Channel | None = "worker",
    ) -> ReviewItem:
        """Create a ``pending`` item with deadlines computed from the resolved policy."""
        policy = self._policies.resolve(kind, action_kind)
        try:
            item = ReviewItem.model_validate(
                {
                    "item_id": self._ids(),
                    "kind": kind,
                    "state": "pending",
                    "cloud": domain_id.split(":", 1)[0],
                    "customer_id": customer_id,
                    "domain_id": domain_id,
                    "subject_ref": subject_ref,
                    "action_kind": action_kind,
                    "intent_id": intent_id,
                    "confirmation_hash": confirmation_hash,
                    "maker_principal_id": maker_principal_id,
                    "maker_on_behalf_of_principal_id": maker_on_behalf_of_principal_id,
                    "maker": maker,
                    "created_at": now,
                    "sla_due_at": now + policy.sla,
                    "expires_at": now + policy.expiry,
                    "policy_version": policy.policy_version,
                }
            )
        except ValidationError as exc:
            raise InvalidSchemaError("invalid review item", reason="invalid_review_item") from exc
        ctx = audit_context(
            actor=opened_by,
            scope_hash=scope_hash,
            correlation_id=correlation_id,
            operation="hitl.review.open",
            channel=channel,
            intent_id=intent_id,
        )
        return await self._audited_write(
            ctx, item, lambda: self._store.create(item), detail=f"review_opened={kind}"
        )

    async def get(self, item_id: str) -> ReviewItem | None:
        return await self._store.get(item_id)

    async def decisions(self, item_id: str) -> list[ImmutableDecision]:
        return await self._decisions.list_for_item(item_id)

    # -- assign ----------------------------------------------------------------------------

    async def assign(
        self,
        item_id: str,
        assignee_principal_id: str | None,
        by_principal_id: str,
        now: datetime,
        *,
        by: Actor,
        scope_hash: str,
        correlation_id: str,
        assignee: Actor | None = None,
        channel: Channel | None = "rest",
    ) -> ReviewItem:
        """Claim (``assignee_principal_id=None``) or assign to another authorized reviewer."""
        item = await self._require(item_id)
        policy = self.policy_for(item)
        ctx = audit_context(
            actor=by,
            scope_hash=scope_hash,
            correlation_id=correlation_id,
            operation="hitl.review.assign",
            channel=channel,
            intent_id=item.intent_id,
        )
        target_id = assignee_principal_id or by_principal_id
        target_actor = by if assignee_principal_id is None else assignee

        async def check() -> None:
            if item.state_name not in _ASSIGNABLE:
                raise StaleVersionError("review item is final", reason="review_item_final")
            if target_actor is None:
                raise InvalidSchemaError(
                    "assigning another reviewer needs their pseudonymous actor",
                    reason="assignee_actor_required",
                )
            await self._authorize(by_principal_id, item, policy)
            if target_id != by_principal_id:
                await self._authorize(target_id, item, policy)
            self._check_separation(target_id, target_actor, item, policy)

        await self._guard(ctx, item, check)
        updated = transition(
            item,
            "assigned",
            assignee_principal_id=target_id,
            assignee=target_actor,
            assigned_at=now,
            assignment_due_at=now + policy.assignment_timeout,
        )
        stored = await self._replace(ctx, item, updated, detail="review_assigned")
        if target_actor is not None:
            await self._notify(
                stored, "review_assigned", target_actor.principal_pseudonym, correlation_id
            )
        return stored

    # -- decide ----------------------------------------------------------------------------

    async def decide(
        self,
        item_id: str,
        reviewer_principal_id: str,
        reviewer: Actor,
        decision: Literal["approved", "rejected"],
        reason: str,
        confirmation_hash: str | None,
        now: datetime,
        correlation_id: str,
        *,
        scope_hash: str,
        channel: Channel | None = "rest",
    ) -> ImmutableDecision:
        """Record one immutable decision and move the item to ``approved`` / ``rejected``."""
        item = await self._require(item_id)
        policy = self.policy_for(item)
        ctx = audit_context(
            actor=reviewer,
            scope_hash=scope_hash,
            correlation_id=correlation_id,
            operation=f"hitl.decide.{item.review_kind}",
            channel=channel,
            intent_id=item.intent_id,
        )

        async def check() -> None:
            if item.state_name not in DECIDABLE_STATES:
                raise StaleVersionError("review item is already final", reason="review_item_final")
            if decision not in ("approved", "rejected"):
                raise InvalidSchemaError(
                    "decision must be approved or rejected", reason="bad_decision"
                )
            await self._authorize(reviewer_principal_id, item, policy)
            self._check_separation(reviewer_principal_id, reviewer, item, policy)
            if (
                item.state_name == "assigned"
                and item.assignee_principal_id != reviewer_principal_id
            ):
                raise ForbiddenError(
                    "review item is assigned to another reviewer",
                    reason="review_item_assigned_to_other",
                )
            self._check_confirmation(item, confirmation_hash)

        await self._guard(ctx, item, check)
        try:
            record = ImmutableDecision.model_validate(
                {
                    "schema_version": DECISION_SCHEMA_VERSION,
                    "decision_id": self._ids(),
                    "review_item_id": item.item_id,
                    "review_kind": item.review_kind,
                    "intent_id": item.intent_id,
                    "approved_confirmation_hash": item.confirmation_hash,
                    "reviewer": reviewer.model_dump(mode="json"),
                    "maker": None if item.maker is None else item.maker.model_dump(mode="json"),
                    "self_approval_allowed": not policy.self_approval_forbidden,
                    "decision": decision,
                    "reason": reason,
                    "policy_version": policy.policy_version,
                    "decided_at": format_timestamp(now),
                    "correlation_id": correlation_id,
                }
            )
        except ValidationError as exc:
            await self._audit_denied(
                ctx, item, InvalidSchemaError("invalid decision", reason="invalid_decision")
            )
            raise InvalidSchemaError("invalid decision", reason="invalid_decision") from exc
        stored = await self._decisions.append(
            record,
            cloud=item.cloud,
            customer_id=item.customer_id,
            domain_id=item.domain_id,
            scope_hash=scope_hash,
            channel=channel,
        )
        updated = transition(
            item, decision, decision_id=stored.decision_id.root, decided_at=now, **_UNASSIGNED
        )
        await self._replace(ctx, item, updated, detail=f"review_{decision}")
        return stored

    # -- outcome of the approved action (item 4) -------------------------------------------

    async def mark_executed(
        self,
        item_id: str,
        now: datetime,
        *,
        correlation_id: str,
        actor: Actor = SYSTEM_ACTOR,
        scope_hash: str = SYSTEM_SCOPE_HASH,
    ) -> ReviewItem:
        return await self._mark(item_id, "executed", correlation_id, actor, scope_hash)

    async def mark_failed(
        self,
        item_id: str,
        now: datetime,
        *,
        correlation_id: str,
        actor: Actor = SYSTEM_ACTOR,
        scope_hash: str = SYSTEM_SCOPE_HASH,
    ) -> ReviewItem:
        return await self._mark(item_id, "failed", correlation_id, actor, scope_hash)

    async def _mark(
        self,
        item_id: str,
        target: Literal["executed", "failed"],
        correlation_id: str,
        actor: Actor,
        scope_hash: str,
    ) -> ReviewItem:
        item = await self._require(item_id)
        ctx = audit_context(
            actor=actor,
            scope_hash=scope_hash,
            correlation_id=correlation_id,
            operation=f"hitl.review.{target}",
            channel="worker",
            intent_id=item.intent_id,
        )

        async def check() -> None:
            if item.kind != "maker_checker":
                raise InvalidSchemaError(
                    "only maker_checker items record an action outcome",
                    reason="not_maker_checker",
                )
            if item.state_name != "approved":
                raise StaleVersionError(
                    f"review item is {item.state_name}, not approved",
                    reason="invalid_review_transition",
                )

        await self._guard(ctx, item, check)
        return await self._replace(ctx, item, transition(item, target), detail=f"review_{target}")

    # -- timers ----------------------------------------------------------------------------

    async def apply_timers(
        self, item: ReviewItem, now: datetime, *, correlation_id: str
    ) -> TimerOutcome:
        """Evaluate the stored deadlines, persist under the ETag, then notify. Restart-safe."""
        actions = evaluate_timers(item, self.policy_for(item), now)
        if not actions:
            return TimerOutcome(item=item)
        updated = item
        for action in actions:
            updated = apply_timer_action(updated, action)
        ctx = audit_context(
            actor=SYSTEM_ACTOR,
            scope_hash=SYSTEM_SCOPE_HASH,
            correlation_id=correlation_id,
            operation="hitl.review.timer",
            channel="worker",
            intent_id=item.intent_id,
        )
        detail = "timer=" + "+".join(a.kind for a in actions)
        try:
            stored = await self._replace(ctx, item, updated, detail=detail)
        except StaleVersionError:
            # Another worker (or a reviewer) changed the item first: it won. Skip, never redo.
            return TimerOutcome(item=item, conflict=True)
        failed = 0
        for action in actions:
            failed += await self._notify(
                stored,
                action.notification_event,
                _recipient(action, item, stored),
                correlation_id,
            )
        return TimerOutcome(item=stored, applied=tuple(actions), notifications_failed=failed)

    # -- internals -------------------------------------------------------------------------

    async def _require(self, item_id: str) -> ReviewItem:
        item = await self._store.get(item_id)
        if item is None:
            raise ForbiddenError("review item not found", reason="review_item_not_found")
        return item

    async def _authorize(self, principal_id: str, item: ReviewItem, policy: ReviewPolicy) -> None:
        allowed = await self._authorizer.can_review(
            principal_id, item.customer_id, item.domain_id, policy.approver_permission
        )
        if not allowed:
            raise ForbiddenError(
                "principal may not review this item", reason="reviewer_not_authorized"
            )

    @staticmethod
    def _check_separation(
        principal_id: str, actor: Actor | None, item: ReviewItem, policy: ReviewPolicy
    ) -> None:
        """Primary rule: real principal ids. Secondary: the contract's pseudonym rule."""
        if not policy.self_approval_forbidden:
            return
        makers = {p for p in (item.maker_principal_id, item.maker_on_behalf_of_principal_id) if p}
        if principal_id in makers:
            raise ForbiddenError(
                "the maker cannot review their own change", reason="self_approval_forbidden"
            )
        if actor is not None and item.maker is not None:
            maker_names = {item.maker.principal_pseudonym, item.maker.on_behalf_of} - {None}
            if actor.principal_pseudonym in maker_names:
                raise ForbiddenError(
                    "the maker cannot review their own change", reason="self_approval_forbidden"
                )

    @staticmethod
    def _check_confirmation(item: ReviewItem, confirmation_hash: str | None) -> None:
        if item.kind != "maker_checker":
            if confirmation_hash is not None:
                raise InvalidSchemaError(
                    "insight reviews carry no confirmation hash",
                    reason="confirmation_hash_not_applicable",
                )
            return
        if confirmation_hash is None or not digests_equal(
            confirmation_hash, item.confirmation_hash
        ):
            raise InvalidSchemaError(
                "approval does not match the confirmed change",
                reason="confirmation_hash_mismatch",
            )

    async def _guard(
        self, ctx: AuditContext, item: ReviewItem, check: Callable[[], Awaitable[None]]
    ) -> None:
        """Run ``check``; on any taxonomy refusal write a ``denied`` record, then re-raise."""
        try:
            await check()
        except NeuroSphereError as exc:
            await self._audit_denied(ctx, item, exc)
            raise

    async def _audit_denied(
        self, ctx: AuditContext, item: ReviewItem, exc: NeuroSphereError
    ) -> None:
        await self._audit.append(
            audit_chain_for(item.customer_id, item.domain_id),
            build_denied(ctx, code=exc.code, reason=refusal_code(exc), subject=item_subject(item)),
        )

    async def _replace(
        self, ctx: AuditContext, before: ReviewItem, after: ReviewItem, *, detail: str
    ) -> ReviewItem:
        if before.etag is None:
            raise StaleVersionError("review item has no stored version", reason="etag_mismatch")
        etag = before.etag
        return await self._audited_write(
            ctx, before, lambda: self._store.replace(after, if_match=etag), detail=detail
        )

    async def _audited_write(
        self,
        ctx: AuditContext,
        before: ReviewItem,
        write: Callable[[], Awaitable[ReviewItem]],
        *,
        detail: str,
    ) -> ReviewItem:
        async def mutate() -> ReviewItem:
            stored = await write()
            if stored.etag is None:
                raise DependencyTransientError(
                    "review store returned no version", reason="hitl_store_unavailable"
                )
            return stored

        def failed(exc: BaseException) -> AuditDraft:
            return build_after(
                ctx, item_subject(before), result="failed", verified=False, detail=refusal_code(exc)
            )

        def succeeded(stored: ReviewItem) -> AuditDraft:
            return build_after(
                ctx, item_subject(stored), result="succeeded", verified=True, detail=detail
            )

        return await run_audited_mutation(
            self._audit,
            audit_chain_for(before.customer_id, before.domain_id),
            before=build_before(ctx, item_subject(before)),
            mutate=mutate,
            after=succeeded,
            on_error=failed,
        )

    async def _notify(
        self, item: ReviewItem, event: NotificationEvent, recipient: str, correlation_id: str
    ) -> int:
        """Send through every notifier; return how many failed (failures are logged, not raised)."""
        if not self._notifiers:
            return 0
        notification = Notification(
            notification_id=self._ids(),
            event=event,
            review_item_id=item.item_id,
            cloud=item.cloud,
            customer_id=item.customer_id,
            domain_id=item.domain_id,
            recipient_ref=recipient,
            escalation_level=item.escalation_level,
            correlation_id=correlation_id,
        )
        failed = 0
        for notifier in self._notifiers:
            try:
                await notifier.send(notification)
            except NeuroSphereError as exc:
                failed += 1
                logger.warning(
                    "notification not recorded",
                    extra={"event": "hitl.notify_failed", "reason": refusal_code(exc)},
                )
        return failed


def _recipient(action: TimerAction, before: ReviewItem, after: ReviewItem) -> str:
    """Routing reference for a timer notification (a pseudonym or a queue ref, never an address)."""
    if action.kind == "return_to_pending" and before.assignee is not None:
        return before.assignee.principal_pseudonym
    if action.kind == "escalate":
        return f"escalation.level-{after.escalation_level}"
    if action.kind == "cap_escalation":
        return "escalation.capped"
    return "review.queue"
