"""Request and response models for ``/api/v1/lifecycle`` (PRP-23 item 3).

Bodies carry no customer or domain field. The scope comes from the bearer token only; an extra
``customer_id`` or ``domain_id`` in a body is ignored (``extra="ignore"``), never read.

No ``from __future__ import annotations``: FastAPI and pydantic inspect these.
"""

from datetime import datetime
from typing import Literal

from neurosphere_core.lifecycle import (
    ActionKind,
    LegalHold,
    LifecycleOutcome,
    LifecycleRequest,
    TargetRef,
)
from neurosphere_core.lifecycle.models import RecordId, SubjectId, Token
from neurosphere_core.lifecycle.policy import PolicyState
from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator

__all__ = [
    "HoldCreate",
    "HoldView",
    "RequestAccepted",
    "RequestCreate",
    "RequestView",
    "StatusView",
]


class HoldCreate(BaseModel):
    """A legal hold selects by any combination of fields; every given selector must match."""

    model_config = ConfigDict(extra="ignore")

    reason_code: Token
    target_kind: Token | None = None
    record_id: RecordId | None = None
    subject_id: SubjectId | None = None
    data_class: Token | None = None
    custodians: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _has_selector(self) -> "HoldCreate":
        if not (self.target_kind or self.record_id or self.subject_id or self.data_class):
            raise ValueError("a legal hold needs at least one selector")
        return self


class HoldView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hold_id: str
    reason_code: str
    target_kind: str | None
    record_id: str | None
    subject_id: str | None
    data_class: str | None
    custodians: tuple[str, ...]
    placed_at: AwareDatetime

    @classmethod
    def of(cls, hold: LegalHold) -> "HoldView":
        return cls(
            hold_id=hold.hold_id,
            reason_code=hold.reason_code,
            target_kind=hold.target_kind,
            record_id=hold.record_id,
            subject_id=hold.subject_id,
            data_class=hold.data_class,
            custodians=hold.custodians,
            placed_at=hold.placed_at,
        )


class RequestCreate(BaseModel):
    """Ask for a lifecycle action. ``export`` is not a job (it runs synchronously)."""

    model_config = ConfigDict(extra="ignore")

    action: ActionKind
    target: TargetRef | None = None
    subject_id: SubjectId | None = None
    #: A job can only make a run safer: the worker mode decides, this can add dry-run, never remove.
    dry_run: bool = False

    @model_validator(mode="after")
    def _shape(self) -> "RequestCreate":
        # Reuse the engine's own shape rules (export refused, target or subject required).
        self.to_request()
        return self

    def to_request(self) -> LifecycleRequest:
        return LifecycleRequest(action=self.action, target=self.target, subject_id=self.subject_id)


class RequestAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    state: Literal["pending", "queued", "done"]
    deduplicated: bool = False


class RequestView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    action: ActionKind
    state: Literal["pending", "queued", "done"]
    dry_run: bool
    requested_by: str
    submitted_at: datetime
    updated_at: datetime | None = None
    outcome: LifecycleOutcome | None = None


class StatusView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: ``dry_run`` (the default: nothing is mutated) or ``execute``.
    mode: Literal["dry_run", "execute"]
    policy_status: Literal["set", "unset"]
    #: ``not_configured``, ``file_unreadable`` or ``invalid`` when the policy is unset.
    policy_problem: str | None = None
    policy_version: str | None = None
    #: Jobs requested and not yet final (pending plus deferred behind a hold or retention).
    queue_depth: int
    active_holds: int

    @classmethod
    def of(cls, *, mode: str, policy: PolicyState, depth: int, holds: int) -> "StatusView":
        return cls(
            mode="execute" if mode == "execute" else "dry_run",
            policy_status=policy.status,
            policy_problem=policy.problem,
            policy_version=policy.policy.policy_version if policy.policy is not None else None,
            queue_depth=depth,
            active_holds=holds,
        )
