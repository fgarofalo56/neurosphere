"""Request bodies and response views of the action API (PRP-17 wire contract).

Bodies carry only what the surface decides: the change (kind, target, version, diff, evidence)
and the idempotency key. Identity, customer, domain, ids, timestamps and state are server-side;
``extra="forbid"`` makes a smuggled ``actor`` / ``customer_id`` / ``principal_id`` a 422.

Views expose the contract ``ActionIntent`` (pseudonymous actor) plus derived flags. The
server-only ``StoredIntent`` envelope (real principal id, partition, ETag, payload digest) never
leaves the API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from neurosphere_contracts.actions.v1.action_intent import ActionIntent, EvidenceRef, ProposedDiff
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_core.actions import (
    CanaryOutcome,
    DraftRequest,
    ExecutionPhase,
    StoredIntent,
    intent_to_wire,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "ActionList",
    "ActionView",
    "ConfirmBody",
    "DecisionBody",
    "DraftIntentBody",
    "EmergencyDisableBody",
    "EmergencyDisableView",
    "ExecutionView",
]

_HASH = r"^sha256:[0-9a-f]{64}$"
_REASON = r"^[a-z][a-z0-9_]{0,63}$"

ConfirmationHash = Annotated[str, Field(pattern=_HASH)]
Channel = Literal["button", "chat", "rest", "mcp"]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftIntentBody(_Body):
    """``POST .../intents``. ``channel`` is metadata only (audit, display); never hashed."""

    action_kind: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    target: TargetRef
    target_version: Annotated[str, Field(min_length=1, max_length=256)]
    proposed_diff: ProposedDiff
    evidence: list[EvidenceRef] = Field(default_factory=list[EvidenceRef], max_length=64)
    idempotency_key: Annotated[str, Field(pattern=r"^[A-Za-z0-9._:-]{16,128}$")]
    channel: Channel = "rest"
    dry_run: bool = False

    def to_draft_request(self) -> DraftRequest:
        return DraftRequest(
            action_kind=self.action_kind,
            target=self.target,
            target_version=self.target_version,
            proposed_diff=self.proposed_diff,
            evidence=list(self.evidence),
            idempotency_key=self.idempotency_key,
            channel=self.channel,
            dry_run=self.dry_run,
        )


class ConfirmBody(_Body):
    """``POST .../confirm``: the hash the maker was shown (``awaiting_confirmation``)."""

    confirmation_hash: ConfirmationHash


class DecisionBody(_Body):
    """``POST .../decisions`` (maker-checker). ``reason`` is the reviewer's justification."""

    decision: Literal["approved", "rejected"]
    reason: Annotated[str, Field(min_length=1, max_length=2048)]
    confirmation_hash: ConfirmationHash


class EmergencyDisableBody(_Body):
    """``PUT /emergency-disable``. ``reason`` is a snake_case code, required when disabling."""

    disabled: bool
    reason: Annotated[str | None, Field(pattern=_REASON)] = None

    @model_validator(mode="after")
    def _disable_needs_reason(self) -> Self:
        if self.disabled and self.reason is None:
            raise ValueError("disabling execution requires a reason code")
        return self


class ExecutionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: ExecutionPhase
    canary: CanaryOutcome | None
    verify_matched: bool | None
    rolled_back: bool


class ActionView(BaseModel):
    """Wire-contract ``ActionView``: the intent plus derived flags, never the envelope."""

    model_config = ConfigDict(extra="forbid")

    intent: ActionIntent
    advisory: bool
    requires_approval: bool
    self_approval_forbidden: bool
    review_item_id: str | None
    execution: ExecutionView | None

    @classmethod
    def build(
        cls,
        stored: StoredIntent,
        *,
        advisory: bool,
        requires_approval: bool,
        self_approval_forbidden: bool,
    ) -> ActionView:
        record = stored.execution
        execution = (
            None
            if record is None
            else ExecutionView(
                phase=record.phase,
                canary=record.canary,
                verify_matched=record.verify_matched,
                rolled_back=record.rolled_back,
            )
        )
        return cls(
            # Rebuilt from the contract wire form so only members the contract carries are set;
            # routes render with ``response_model_exclude_unset`` and the JSON a client receives
            # hashes to ``confirmation_hash`` (no ``"from": null`` on a replace op).
            intent=ActionIntent.model_validate(intent_to_wire(stored.intent)),
            advisory=advisory,
            requires_approval=requires_approval,
            self_approval_forbidden=self_approval_forbidden,
            review_item_id=stored.review_item_id,
            execution=execution,
        )


class ActionList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ActionView]
    next_cursor: str | None


class EmergencyDisableView(BaseModel):
    """Kill-switch state for the caller's customer. ``changed_by`` is a pseudonym."""

    model_config = ConfigDict(extra="forbid")

    disabled: bool
    reason: str | None
    changed_by: str | None
    changed_at: datetime | None
