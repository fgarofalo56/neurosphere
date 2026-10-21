"""Per-action-kind API policy: maker-checker requirement and confirmation lifetimes.

``requires_approval`` is looked up per ``action_kind``; an unknown kind requires approval
(fail closed, never a permissive default). When approval is required the confirmation is
presented with ``approval_confirmation_ttl`` (default 24h) instead of ``confirmation_ttl``
(default 15 min, wire contract), because the approval must land before the confirmation expires.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final, Self

from neurosphere_core.actions import DEFAULT_CONFIRMATION_TTL
from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "DEFAULT_ACTION_KINDS",
    "DEFAULT_APPROVAL_CONFIRMATION_TTL",
    "ActionApiSettings",
    "ActionKindPolicy",
]

DEFAULT_APPROVAL_CONFIRMATION_TTL: Final = timedelta(hours=24)
_MIN_TTL: Final = timedelta(seconds=30)
_MAX_TTL: Final = timedelta(days=7)


class ActionKindPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requires_approval: bool = True


DEFAULT_ACTION_KINDS: Final[dict[str, ActionKindPolicy]] = {
    "model_deployment_swap": ActionKindPolicy(requires_approval=True),
}


class ActionApiSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    confirmation_ttl: timedelta = DEFAULT_CONFIRMATION_TTL
    approval_confirmation_ttl: timedelta = DEFAULT_APPROVAL_CONFIRMATION_TTL
    action_kinds: dict[str, ActionKindPolicy] = Field(
        default_factory=lambda: dict(DEFAULT_ACTION_KINDS)
    )

    @model_validator(mode="after")
    def _ttls_in_range(self) -> Self:
        for name in ("confirmation_ttl", "approval_confirmation_ttl"):
            value: timedelta = getattr(self, name)
            if not _MIN_TTL <= value <= _MAX_TTL:
                raise ValueError(f"{name} must be between 30 seconds and 7 days")
        return self

    def requires_approval(self, action_kind: str) -> bool:
        policy = self.action_kinds.get(action_kind)
        return True if policy is None else policy.requires_approval

    def confirmation_ttl_for(self, action_kind: str) -> timedelta:
        if self.requires_approval(action_kind):
            return self.approval_confirmation_ttl
        return self.confirmation_ttl
