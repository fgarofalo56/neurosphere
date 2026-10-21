"""Request bodies and views of the review queue API (PRP-17 wire contract).

``ReviewItemView`` exposes pseudonyms only: the real maker, on-behalf-of and assignee principal
ids on the stored ``ReviewItem`` never leave the server. ``decisions`` lists every logged
``ApprovalDecision`` of the item; ``effective_decision_id`` names the one that took effect and
``superseded_decision_ids`` the others (a decision that lost a concurrent race stays in the
append-only log as history but never took effect).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Literal

from neurosphere_contracts.actions.v1.approval_decision import ApprovalDecision
from neurosphere_core.hitl import ReviewItem, ReviewKind, ReviewStateName
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AssignmentBody",
    "ReviewDecisionBody",
    "ReviewItemList",
    "ReviewItemView",
]

_PRINCIPAL = r"^[A-Za-z0-9][A-Za-z0-9._:/=@-]{0,511}$"


class AssignmentBody(BaseModel):
    """``null`` claims the item for the caller; a principal id assigns another reviewer."""

    model_config = ConfigDict(extra="forbid")

    assignee_principal_id: Annotated[str | None, Field(pattern=_PRINCIPAL)] = None


class ReviewDecisionBody(BaseModel):
    """Maker-checker decisions carry the confirmation hash; insight decisions must not."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]
    reason: Annotated[str, Field(min_length=1, max_length=2048)]
    confirmation_hash: Annotated[str | None, Field(pattern=r"^sha256:[0-9a-f]{64}$")] = None


class ReviewItemView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    kind: ReviewKind
    state: ReviewStateName
    domain_id: str
    subject_ref: str
    intent_id: str | None
    assignee_pseudonym: str | None
    sla_due_at: datetime
    escalation_level: int
    created_at: datetime
    decisions: list[ApprovalDecision]
    effective_decision_id: str | None
    superseded_decision_ids: list[str]

    @classmethod
    def build(cls, item: ReviewItem, decisions: Sequence[ApprovalDecision]) -> ReviewItemView:
        effective = item.decision_id
        plain = [ApprovalDecision.model_validate(d.model_dump(mode="json")) for d in decisions]
        return cls(
            item_id=item.item_id,
            kind=item.kind,
            state=item.state_name,
            domain_id=item.domain_id,
            subject_ref=item.subject_ref,
            intent_id=item.intent_id,
            assignee_pseudonym=None if item.assignee is None else item.assignee.principal_pseudonym,
            sla_due_at=item.sla_due_at,
            escalation_level=item.escalation_level,
            created_at=item.created_at,
            decisions=plain,
            effective_decision_id=effective,
            superseded_decision_ids=[
                d.decision_id.root for d in plain if d.decision_id.root != effective
            ],
        )


class ReviewItemList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ReviewItemView]
    next_cursor: str | None
