# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StrictBool,
    StrictInt,
    StrictStr,
)

from . import common


class ReviewKind(
    RootModel[
        Literal[
            "maker_checker",
            "relationship",
            "evaluation_dispute",
            "recommendation",
            "policy_exception",
        ]
    ]
):
    root: Literal[
        "maker_checker", "relationship", "evaluation_dispute", "recommendation", "policy_exception"
    ]


class DurationSeconds(RootModel[StrictInt]):
    root: Annotated[StrictInt, Field(ge=1, le=7776000)]
    """
    Positive duration in whole seconds, at most 90 days.
    """


class ReviewPolicySettings(BaseModel):
    """
    One core ReviewPolicy. Every duration is positive.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    self_approval_forbidden: StrictBool
    approver_permission: Literal["action.approve", "catalog.curate"]
    """
    Permission the reviewer needs on the item's domain.
    """
    assignment_timeout_seconds: DurationSeconds
    sla_seconds: DurationSeconds
    escalation_step_seconds: DurationSeconds
    max_escalations: Annotated[StrictInt, Field(ge=0, le=10)]
    expiry_seconds: DurationSeconds


class ReviewKindDefault(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    review_kind: ReviewKind
    policy: ReviewPolicySettings


class ReviewActionOverride(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    review_kind: ReviewKind
    action_kind: Annotated[StrictStr, Field(pattern="^[a-z][a-z0-9_]{0,63}$")]
    """
    Action kind (actions/v1 ActionIntent action_kind).
    """
    policy: ReviewPolicySettings


class ReviewPolicyDocument(BaseModel):
    """
    Operator review policy (PRP-44), mapping onto core HITL ReviewPolicyRegistry: kind_defaults become the per-review-kind defaults and action_overrides the (review_kind, action_kind) overrides. Durations are integer seconds (core ReviewPolicy timedeltas). A kind missing from kind_defaults has no policy and fails closed (capability_unavailable), so maker_checker is required. Self-approval stays forbidden unless an override says otherwise. Rules JSON Schema cannot express are checked by tests/contracts/validators.py::check_review_policy_document: review kinds in kind_defaults and (review_kind, action_kind) pairs in action_overrides are unique.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    policy_version: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]
    """
    Version label copied onto every ReviewPolicy built from this document.
    """
    kind_defaults: Annotated[list[ReviewKindDefault], Field(max_length=16, min_length=1)]
    action_overrides: Annotated[list[ReviewActionOverride], Field(max_length=64)]
