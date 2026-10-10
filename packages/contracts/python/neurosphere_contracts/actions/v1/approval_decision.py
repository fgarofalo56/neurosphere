# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictBool, StrictStr

from . import actor


class Uuid(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(pattern="^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
    ]


class UtcTimestamp(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]{1,9})?Z$"),
    ]
    """
    RFC 3339 timestamp in UTC (`Z` suffix required).
    """


class Sha256Hash(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^sha256:[0-9a-f]{64}$")]


class ApprovalDecision(BaseModel):
    """
    Immutable decision on a HITL review item (PRD NS-04). Written once and never updated: a changed mind is a new review item with a new decision, never an edit, so the schema has no update-capable field. Insight review and maker-checker approval of executable changes are separate kinds. A maker-checker approval binds to the exact confirmation_hash it approves, so an approval cannot be replayed against a different target, version or diff. Rules JSON Schema cannot express are checked by `validate_maker_checker_separation` in tests/contracts/test_action_transitions.py: when self_approval_allowed is false, reviewer.principal_pseudonym differs from maker.principal_pseudonym and from maker.on_behalf_of.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: Annotated[StrictStr, Field(pattern="^1\\.[0-9]+\\.[0-9]+$")]
    decision_id: Uuid
    """
    Server-assigned identifier of this decision (lowercase UUID).
    """
    review_item_id: Uuid
    """
    Review item this decision closes or escalates (lowercase UUID).
    """
    review_kind: Literal["maker_checker", "insight_review"]
    """
    `maker_checker` approves an executable ActionIntent; `insight_review` covers relationship, evaluation, recommendation and policy-exception reviews that execute nothing.
    """
    intent_id: Uuid | None
    """
    ActionIntent under review; required for maker_checker, null for insight_review.
    """
    approved_confirmation_hash: Sha256Hash | None
    """
    confirmation_hash of the exact intent the reviewer saw; required for maker_checker. The executor refuses to proceed when it differs from the intent's current confirmation_hash.
    """
    reviewer: actor.Actor
    """
    Checker: the principal who made this decision.
    """
    maker: actor.Actor | None
    """
    Maker: the principal who authored the change under review; required for maker_checker, null for insight_review.
    """
    self_approval_allowed: StrictBool
    """
    Policy outcome at decision time: whether the maker may also be the checker. False prohibits self-approval (see `validate_maker_checker_separation`).
    """
    decision: Literal["approved", "rejected", "escalated"]
    """
    Outcome. `escalated` moves the review item to a higher reviewer without approving or rejecting.
    """
    reason: Annotated[StrictStr, Field(max_length=2048, min_length=1)]
    """
    Reviewer's justification. Required and non-empty for every decision.
    """
    policy_version: Annotated[StrictStr, Field(max_length=128, min_length=1)]
    """
    Version of the approval policy evaluated for this decision.
    """
    decided_at: UtcTimestamp
    """
    Server-assigned, immutable instant of the decision.
    """
    correlation_id: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9._-]{1,128}$")]
