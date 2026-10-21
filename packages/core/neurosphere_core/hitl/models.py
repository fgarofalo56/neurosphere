"""HITL review item model and the allowlisted review-state transition table (PRP-17 item 3).

A :class:`ReviewItem` is the server-side record of one human-in-the-loop review. It carries the
REAL principal ids (``maker_principal_id``, ``assignee_principal_id``) next to their pseudonymous
``Actor`` references. The real ids are server-only: they exist so self-approval and authorization
compare authenticated principals rather than pseudonyms, display names or sessions. API views
(``ReviewItemView``, item 4) expose pseudonyms only.

State changes go through :func:`transition`, which consults :data:`REVIEW_TRANSITIONS`. Any pair
not listed raises ``stale_version`` (reason ``invalid_review_transition``); nothing is coerced.
Two self-pairs are listed on purpose: ``assigned -> assigned`` (reassignment to another reviewer)
and ``escalated -> escalated`` (a further escalation level while still unclaimed).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Annotated, Final, Literal

from neurosphere_contracts.actions.v1.actor import Actor
from neurosphere_contracts.actions.v1.review_item_state import ReviewItemState
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from neurosphere_core.errors import StaleVersionError

__all__ = [
    "DECIDABLE_STATES",
    "FINAL_STATES",
    "INSIGHT_KINDS",
    "REVIEW_TRANSITIONS",
    "ReviewItem",
    "ReviewKind",
    "ReviewStateName",
    "format_timestamp",
    "is_allowed_transition",
    "review_kind_for",
    "transition",
]

ReviewKind = Literal[
    "maker_checker", "relationship", "evaluation_dispute", "recommendation", "policy_exception"
]
ReviewStateName = Literal[
    "pending", "assigned", "approved", "rejected", "expired", "escalated", "executed", "failed"
]
DecisionReviewKind = Literal["maker_checker", "insight_review"]

INSIGHT_KINDS: Final[frozenset[str]] = frozenset(
    {"relationship", "evaluation_dispute", "recommendation", "policy_exception"}
)

#: Allowlist of (from, to) review-state pairs. Everything else is refused.
REVIEW_TRANSITIONS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "pending": frozenset({"assigned", "escalated", "expired", "approved", "rejected"}),
        "assigned": frozenset(
            {"assigned", "pending", "escalated", "expired", "approved", "rejected"}
        ),
        "escalated": frozenset({"assigned", "escalated", "expired", "approved", "rejected"}),
        # approved is final for decisions; only a maker_checker item moves on, once its action
        # has finished (item 4 reports the executor's outcome).
        "approved": frozenset({"executed", "failed"}),
        "rejected": frozenset(),
        "expired": frozenset(),
        "executed": frozenset(),
        "failed": frozenset(),
    }
)

#: States in which a reviewer may still record a decision.
DECIDABLE_STATES: Final[frozenset[str]] = frozenset({"pending", "assigned", "escalated"})
#: States no timer touches any more (a decision was made or the item ended).
FINAL_STATES: Final[frozenset[str]] = frozenset(
    {"approved", "rejected", "expired", "executed", "failed"}
)

_UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_CANON = r"^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+$"
_PRINCIPAL = r"^[A-Za-z0-9][A-Za-z0-9._:/=@-]{0,511}$"
_SHA256 = r"^sha256:[0-9a-f]{64}$"
_SLUG = r"^[a-z0-9][a-z0-9._-]{0,127}$"

Uuid = Annotated[str, Field(pattern=_UUID)]
CanonicalId = Annotated[str, Field(pattern=_CANON, max_length=512)]
PrincipalId = Annotated[str, Field(pattern=_PRINCIPAL)]


def review_kind_for(kind: str) -> DecisionReviewKind:
    """``ApprovalDecision.review_kind`` for a review item kind (insight vs maker-checker)."""
    return "maker_checker" if kind == "maker_checker" else "insight_review"


def format_timestamp(instant: datetime) -> str:
    """Contract ``UtcTimestamp``: RFC 3339, UTC, ``Z`` suffix, microsecond precision."""
    if instant.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    utc = instant.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S") + f".{utc.microsecond:06d}Z"


class ReviewItem(BaseModel):
    """One review. Frozen: every change is a new copy written through an ETag-checked replace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: Uuid
    kind: ReviewKind
    state: ReviewItemState
    cloud: Literal["commercial", "government"]
    customer_id: Annotated[str, Field(pattern=_SLUG)]
    domain_id: CanonicalId
    subject_ref: CanonicalId
    """Canonical id of what is reviewed (the action target, edge, evaluation, ...)."""
    action_kind: Annotated[str, Field(pattern=_SLUG)] | None = None
    """For maker_checker: the action kind the policy was resolved for."""
    intent_id: Uuid | None = None
    confirmation_hash: Annotated[str, Field(pattern=_SHA256)] | None = None
    # -- server-only identity (never serialized into an API view) ---------------------------
    maker_principal_id: PrincipalId | None = None
    maker_on_behalf_of_principal_id: PrincipalId | None = None
    """Real principal an agent/copilot maker acted for; also barred from self-approval."""
    maker: Actor | None = None
    assignee_principal_id: PrincipalId | None = None
    assignee: Actor | None = None
    # -- stored deadlines (the only timer state; restart-safe) ------------------------------
    created_at: AwareDatetime
    assigned_at: AwareDatetime | None = None
    assignment_due_at: AwareDatetime | None = None
    sla_due_at: AwareDatetime
    expires_at: AwareDatetime
    escalation_level: Annotated[int, Field(ge=0)] = 0
    escalation_capped: bool = False
    """True once an SLA breach found the escalation cap reached (so it is handled once)."""
    # -- outcome ----------------------------------------------------------------------------
    decision_id: Uuid | None = None
    """The effective ApprovalDecision (the one whose state change won the ETag race)."""
    decided_at: AwareDatetime | None = None
    policy_version: Annotated[str, Field(min_length=1, max_length=128)]
    etag: str | None = None
    """Store-assigned; ignored on create, required as the precondition on replace."""

    @model_validator(mode="after")
    def _check_shape(self) -> ReviewItem:
        if not self.domain_id.startswith(f"{self.cloud}:{self.customer_id}:"):
            raise ValueError("domain_id must belong to the item's cloud and customer")
        if self.kind == "maker_checker":
            missing = [
                name
                for name in ("intent_id", "confirmation_hash", "maker_principal_id", "maker")
                if getattr(self, name) is None
            ]
            if missing:
                raise ValueError(f"maker_checker items require {', '.join(missing)}")
        elif self.intent_id is not None or self.confirmation_hash is not None:
            raise ValueError("insight review items carry no intent_id or confirmation_hash")
        if (self.assignee_principal_id is None) != (self.state_name != "assigned"):
            raise ValueError("an assignee is present exactly when the item is assigned")
        return self

    @property
    def state_name(self) -> ReviewStateName:
        return self.state.root

    @property
    def review_kind(self) -> DecisionReviewKind:
        return review_kind_for(self.kind)

    @property
    def is_final(self) -> bool:
        return self.state_name in FINAL_STATES

    def active_deadlines(self) -> tuple[datetime, ...]:
        """Deadlines a timer still has to act on (empty once the item is final)."""
        if self.is_final:
            return ()
        found: list[datetime] = [self.expires_at]
        if not self.escalation_capped:
            found.append(self.sla_due_at)
        if self.state_name == "assigned" and self.assignment_due_at is not None:
            found.append(self.assignment_due_at)
        return tuple(found)

    def next_deadline(self) -> datetime | None:
        deadlines = self.active_deadlines()
        return min(deadlines) if deadlines else None


def is_allowed_transition(source: str, target: str) -> bool:
    return target in REVIEW_TRANSITIONS.get(source, frozenset())


def transition(item: ReviewItem, target: ReviewStateName, **changes: object) -> ReviewItem:
    """Copy of ``item`` in state ``target`` (plus ``changes``), or raise if not allowlisted."""
    if not is_allowed_transition(item.state_name, target):
        raise StaleVersionError(
            f"review item cannot move from {item.state_name} to {target}",
            reason="invalid_review_transition",
        )
    data = item.model_dump()
    data.update(changes)
    data["state"] = target
    return ReviewItem.model_validate(data)
