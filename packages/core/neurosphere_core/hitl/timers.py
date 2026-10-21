"""Pure timer evaluation over stored deadlines (PRP-17 clarification 7).

:func:`evaluate_timers` looks only at the item's stored deadlines, the policy and ``now``. It is
deterministic, and idempotent because every action it returns moves or clears the deadline that
triggered it once applied (:func:`apply_timer_action`): re-evaluating the applied item at the
same ``now`` yields nothing. There are no in-memory timers, so a restarted worker reaches the same
decision from the store alone.

Rules, in priority order:

1. ``expires_at <= now`` -> ``expire`` (state ``expired``). Expiry dominates; nothing else runs.
2. SLA breach (``sla_due_at <= now``, not yet capped):
   * ``escalation_level < max_escalations`` -> ``escalate``: state ``escalated``, level + 1, the
     assignee is released, next SLA deadline ``now + escalation_step``.
   * otherwise -> ``cap_escalation``: ``escalation_capped = True`` (handled once; the item waits
     for a decision or for expiry).
3. Assignment timeout (state ``assigned``, ``assignment_due_at <= now``) and no escalation in
   this pass -> ``return_to_pending``: the assignee is released, state ``pending``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from neurosphere_core.hitl.models import ReviewItem, transition
from neurosphere_core.hitl.notify import NotificationEvent
from neurosphere_core.hitl.policy import ReviewPolicy

__all__ = ["TimerAction", "TimerKind", "apply_timer_action", "evaluate_timers"]

TimerKind = Literal["expire", "escalate", "cap_escalation", "return_to_pending"]

_EVENTS: dict[str, NotificationEvent] = {
    "expire": "review_expired",
    "escalate": "review_escalated",
    "cap_escalation": "escalation_capped",
    "return_to_pending": "assignment_timed_out",
}


class TimerAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: TimerKind
    item_id: str
    deadline: AwareDatetime
    """The stored deadline that fired (identifies the action; applying it moves or clears it)."""
    at: AwareDatetime
    """The evaluation instant (``now``)."""
    new_escalation_level: int | None = None
    next_sla_due_at: AwareDatetime | None = None

    @property
    def notification_event(self) -> NotificationEvent:
        return _EVENTS[self.kind]


def evaluate_timers(item: ReviewItem, policy: ReviewPolicy, now: datetime) -> list[TimerAction]:
    if item.is_final:
        return []
    if item.expires_at <= now:
        return [TimerAction(kind="expire", item_id=item.item_id, deadline=item.expires_at, at=now)]
    actions: list[TimerAction] = []
    escalating = False
    if not item.escalation_capped and item.sla_due_at <= now:
        if item.escalation_level < policy.max_escalations:
            escalating = True
            actions.append(
                TimerAction(
                    kind="escalate",
                    item_id=item.item_id,
                    deadline=item.sla_due_at,
                    at=now,
                    new_escalation_level=item.escalation_level + 1,
                    next_sla_due_at=now + policy.escalation_step,
                )
            )
        else:
            actions.append(
                TimerAction(
                    kind="cap_escalation", item_id=item.item_id, deadline=item.sla_due_at, at=now
                )
            )
    if (
        not escalating
        and item.state_name == "assigned"
        and item.assignment_due_at is not None
        and item.assignment_due_at <= now
    ):
        actions.append(
            TimerAction(
                kind="return_to_pending",
                item_id=item.item_id,
                deadline=item.assignment_due_at,
                at=now,
            )
        )
    return actions


_RELEASE = {
    "assignee_principal_id": None,
    "assignee": None,
    "assigned_at": None,
    "assignment_due_at": None,
}


def apply_timer_action(item: ReviewItem, action: TimerAction) -> ReviewItem:
    """The item after ``action`` (pure; the caller persists it with an ETag precondition)."""
    if action.item_id != item.item_id:
        raise ValueError("timer action belongs to another review item")
    if action.kind == "expire":
        return transition(item, "expired", **_RELEASE)
    if action.kind == "escalate":
        return transition(
            item,
            "escalated",
            escalation_level=action.new_escalation_level,
            sla_due_at=action.next_sla_due_at,
            **_RELEASE,
        )
    if action.kind == "cap_escalation":
        return item.model_copy(update={"escalation_capped": True})
    return transition(item, "pending", **_RELEASE)
