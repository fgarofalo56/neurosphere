"""Review policies per review kind and per action kind (PRP-17 clarification 5).

Maker-checker approval of executable changes and insight review (the NS-04 reviewer queue) are
separate kinds with separate defaults:

* ``maker_checker``: approver needs ``action.approve`` on the domain; self-approval is forbidden
  by default and can only be allowed by an explicit per-action-kind policy.
* insight kinds (``relationship``, ``evaluation_dispute``, ``recommendation``,
  ``policy_exception``): reviewer needs ``catalog.curate``. They execute nothing, so there is no
  maker to separate from; ``self_approval_forbidden`` is still honoured when a maker is recorded.

Resolution order: ``(kind, action_kind)`` override, then the kind default. An unknown kind has no
default and raises ``capability_unavailable`` (fail closed, never a permissive fallback).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

from neurosphere_core.auth.scope.permissions import Permission
from neurosphere_core.errors import CapabilityUnavailableError

__all__ = [
    "DEFAULT_POLICY_VERSION",
    "ReviewPolicy",
    "ReviewPolicyRegistry",
    "default_policies",
]

DEFAULT_POLICY_VERSION: Final = "hitl-defaults-1"


class ReviewPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    self_approval_forbidden: bool = True
    approver_permission: Permission
    assignment_timeout: timedelta = timedelta(hours=4)
    """A claimed item not decided within this window returns to ``pending``."""
    sla: timedelta = timedelta(hours=24)
    """Time from creation to the first SLA breach (escalation)."""
    escalation_step: timedelta = timedelta(hours=8)
    """After an escalation, the next SLA deadline is this far after the escalation."""
    max_escalations: Annotated[int, Field(ge=0, le=10)] = 2
    expiry: timedelta = timedelta(days=7)
    """Time from creation after which an undecided item expires."""
    policy_version: Annotated[str, Field(min_length=1, max_length=128)] = DEFAULT_POLICY_VERSION

    @model_validator(mode="after")
    def _positive(self) -> ReviewPolicy:
        for name in ("assignment_timeout", "sla", "escalation_step", "expiry"):
            if getattr(self, name) <= timedelta(0):
                raise ValueError(f"{name} must be positive")
        return self


def default_policies() -> dict[str, ReviewPolicy]:
    insight = ReviewPolicy(approver_permission=Permission.CATALOG_CURATE)
    return {
        "maker_checker": ReviewPolicy(
            approver_permission=Permission.ACTION_APPROVE, self_approval_forbidden=True
        ),
        "relationship": insight,
        "evaluation_dispute": insight,
        "recommendation": insight,
        "policy_exception": insight,
    }


class ReviewPolicyRegistry:
    """Immutable lookup of :class:`ReviewPolicy` by review kind and optional action kind."""

    def __init__(
        self,
        kind_defaults: Mapping[str, ReviewPolicy] | None = None,
        action_overrides: Mapping[tuple[str, str], ReviewPolicy] | None = None,
    ) -> None:
        self._defaults = dict(default_policies() if kind_defaults is None else kind_defaults)
        self._overrides: dict[tuple[str, str], ReviewPolicy] = dict(action_overrides or {})

    def resolve(self, kind: str, action_kind: str | None = None) -> ReviewPolicy:
        """Policy for ``(kind, action_kind)``: the action override, else the kind default."""
        if action_kind is not None:
            override = self._overrides.get((kind, action_kind))
            if override is not None:
                return override
        policy = self._defaults.get(kind)
        if policy is None:
            raise CapabilityUnavailableError(
                "review_policy_missing", detail="no review policy for this review kind"
            )
        return policy
