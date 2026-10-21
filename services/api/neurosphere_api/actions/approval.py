"""The ONE maker-checker approval path (PRP-17 item 4).

Both ``POST /api/v1/actions/domains/{d}/intents/{id}/decisions`` and the review queue's
``POST /api/v1/review/domains/{d}/items/{item}/decisions`` on a ``maker_checker`` item call
:func:`decide_maker_checker`. Nothing else applies an approval to an intent.

Order:

1. Refuse advisory intents (``capability_unavailable`` ``advisory_connector``), an intent that is
   not ``awaiting_approval`` (``invalid_schema`` ``invalid_transition``) and, for an approval, a
   disabled kill switch, BEFORE any decision is recorded.
2. ``HitlService.decide`` records the immutable decision (reviewer authorization, self-approval
   on real principal ids, the item's exact confirmation hash, assignee rule) and moves the item.
3. Re-read the item: only its EFFECTIVE decision (``item.decision_id``) is applied. A decision
   that lost the ETag race stays in the append-only log as history (``stale_version``
   ``decision_superseded``). Approvals are never looked up by intent id.
4. ``ActionService.apply_approval`` re-enforces everything (approver permission recheck,
   self-approval, expiry, hash, the maker's ``action.execute``, kill switch, current target
   version from the connector's ``dry_run``) and moves the intent to ``executing`` (the worker
   picks it up; the API never applies) or ``failed`` (rejected, revoked, target changed).
5. A failed or expired intent marks its approved review item ``failed``.

Safe recovery: when step 4 refuses WITHOUT changing the intent (kill switch flipped, policy store
or connector outage) the item is already ``approved``. The reviewer whose decision is effective
may resend the same decision and hash; it resumes at step 4 and records no second decision.
"""

from __future__ import annotations

from typing import Final, Literal

from neurosphere_core.actions import (
    ActionCaller,
    IntentKey,
    StoredIntent,
    confirmation_hashes_equal,
    require_execution_enabled,
)
from neurosphere_core.actions.errors import (
    ADVISORY_CONNECTOR,
    CONFIRMATION_HASH_MISMATCH,
    ActionValidationError,
    InvalidTransitionError,
)
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    ForbiddenError,
    NeuroSphereError,
    StaleVersionError,
)
from neurosphere_core.hitl import ImmutableDecision, ReviewItem
from neurosphere_core.observability import get_logger

from neurosphere_api.actions.common import probe_target_version
from neurosphere_api.actions.dependencies import ActionPlane

__all__ = ["DECISION_SUPERSEDED", "decide_maker_checker", "effective_decision", "refuse_advisory"]

DECISION_SUPERSEDED: Final = "decision_superseded"
REVIEW_ITEM_MISMATCH: Final = "review_item_mismatch"
_FINISHED: Final = frozenset({"failed", "expired"})
_LOG = get_logger("neurosphere_api.actions")

Decision = Literal["approved", "rejected"]


def refuse_advisory(plane: ActionPlane, stored: StoredIntent) -> None:
    """Advisory intents (no supported write connector) never confirm or approve."""
    if stored.advisory or plane.connector_for(stored.intent.action_kind) is None:
        raise CapabilityUnavailableError(
            ADVISORY_CONNECTOR, "the write connector is advisory; nothing can execute"
        )


async def effective_decision(plane: ActionPlane, item: ReviewItem) -> ImmutableDecision | None:
    """The decision the item's ``decision_id`` names (the one whose state change won)."""
    if item.decision_id is None:
        return None
    for decision in await plane.hitl.decisions(item.item_id):
        if decision.decision_id.root == item.decision_id:
            return decision
    return None


def _check_pairing(stored: StoredIntent, item: ReviewItem) -> None:
    if (
        item.kind != "maker_checker"
        or item.intent_id != stored.intent_id
        or item.customer_id != stored.customer_id
        or item.domain_id != stored.domain_id
        or stored.review_item_id != item.item_id
    ):
        raise ForbiddenError(
            "review item does not belong to this intent", reason=REVIEW_ITEM_MISMATCH
        )


async def _record_or_resume(
    plane: ActionPlane,
    item: ReviewItem,
    caller: ActionCaller,
    decision: Decision,
    reason: str,
    confirmation_hash: str,
) -> tuple[ImmutableDecision, ReviewItem]:
    if item.state_name == "approved":
        # Resume only the effective approval, only for its own reviewer and exact hash.
        found = await effective_decision(plane, item)
        if (
            found is None
            or found.decision != decision
            or found.reviewer.principal_pseudonym != caller.actor.principal_pseudonym
            or not confirmation_hashes_equal(confirmation_hash, item.confirmation_hash)
        ):
            raise StaleVersionError("review item is already decided", reason="review_item_final")
        return found, item
    recorded = await plane.hitl.decide(
        item.item_id,
        caller.principal_id,
        caller.actor,
        decision,
        reason,
        confirmation_hash,
        plane.now(),
        caller.correlation_id,
        scope_hash=caller.scope_hash,
        channel=caller.channel,
    )
    current = await plane.hitl.get(item.item_id)
    if current is None or current.decision_id != recorded.decision_id.root:
        raise StaleVersionError("another decision took effect first", reason=DECISION_SUPERSEDED)
    return recorded, current


async def _mark_item_failed(plane: ActionPlane, item: ReviewItem, caller: ActionCaller) -> None:
    if item.state_name != "approved":
        return
    await plane.hitl.mark_failed(item.item_id, plane.now(), correlation_id=caller.correlation_id)


async def _reconcile(
    plane: ActionPlane, key: IntentKey, item: ReviewItem, caller: ActionCaller
) -> None:
    """After a refused approval: if the intent ended anyway, close its item (best effort)."""
    try:
        latest = await plane.actions.get(key)
        if latest.state in _FINISHED:
            await _mark_item_failed(plane, item, caller)
    except Exception as exc:  # the approval error is the one the caller must see
        _LOG.warning(
            "review item reconciliation failed",
            extra={"event": "actions.reconcile_failed", "error_type": type(exc).__name__},
        )


async def decide_maker_checker(
    plane: ActionPlane,
    *,
    stored: StoredIntent,
    item: ReviewItem,
    caller: ActionCaller,
    decision: Decision,
    reason: str,
    confirmation_hash: str | None,
) -> StoredIntent:
    """Record a maker-checker decision and apply the effective one to the intent."""
    refuse_advisory(plane, stored)
    _check_pairing(stored, item)
    if stored.state != "awaiting_approval":
        raise InvalidTransitionError(
            stored.state, "executing" if decision == "approved" else "failed"
        )
    if confirmation_hash is None:
        raise ActionValidationError(
            CONFIRMATION_HASH_MISMATCH, "a maker-checker decision must carry the confirmation hash"
        )
    if decision == "approved":
        await require_execution_enabled(plane.control, stored.customer_id)
    record, item = await _record_or_resume(plane, item, caller, decision, reason, confirmation_hash)
    approved = record.decision == "approved"
    bound = record.approved_confirmation_hash
    if bound is None:  # contract: required for maker_checker; never apply without it
        raise ActionValidationError(CONFIRMATION_HASH_MISMATCH, "decision carries no hash")
    try:
        current = stored.intent.target_version
        if approved:
            connector = plane.connector_for(stored.intent.action_kind)
            if connector is None:
                refuse_advisory(plane, stored)
            else:
                current = await probe_target_version(connector, stored)
        result = await plane.actions.apply_approval(
            stored.key,
            caller,
            approved=approved,
            approved_confirmation_hash=bound.root,
            current_target_version=current,
            self_approval_forbidden=plane.hitl.policy_for(item).self_approval_forbidden,
            now=plane.now(),
        )
    except NeuroSphereError:
        await _reconcile(plane, stored.key, item, caller)
        raise
    if result.state in _FINISHED:
        await _mark_item_failed(plane, item, caller)
    return result
