"""Retention policy: customer-supplied, never defaulted (PRP-23 clarification 6).

A missing, empty or invalid policy loads as ``unset``. ``unset`` means: nothing is deleted or
expired by the engine, prompt/response bodies are not retained, and the status says so.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from neurosphere_core.lifecycle.models import Token


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RetentionRule(_Frozen):
    data_class: Token
    min_retention_days: int = Field(ge=0)
    max_retention_days: int = Field(ge=1)

    @model_validator(mode="after")
    def _ordered(self) -> RetentionRule:
        if self.max_retention_days < self.min_retention_days:
            raise ValueError("max_retention_days must be >= min_retention_days")
        return self


class RetentionPolicy(_Frozen):
    policy_version: str = Field(min_length=1, max_length=64)
    rules: tuple[RetentionRule, ...] = Field(min_length=1)
    #: Explicit customer opt-in; there is no default (the field is required).
    retain_prompt_response_bodies: bool

    @model_validator(mode="after")
    def _unique(self) -> RetentionPolicy:
        classes = [r.data_class for r in self.rules]
        if len(set(classes)) != len(classes):
            raise ValueError("duplicate data_class in rules")
        return self

    def rule_for(self, data_class: str) -> RetentionRule | None:
        return next((r for r in self.rules if r.data_class == data_class), None)


class PolicyState(_Frozen):
    status: Literal["set", "unset"]
    policy: RetentionPolicy | None = None
    #: Machine code when unset: ``not_configured`` or ``invalid``.
    problem: str | None = None

    @property
    def bodies_retained(self) -> bool:
        """Prompt/response bodies are retained only under a valid policy that opts in."""
        return self.policy is not None and self.policy.retain_prompt_response_bodies


UNSET = PolicyState(status="unset", problem="not_configured")


def load_policy(raw: Mapping[str, Any] | None) -> PolicyState:
    """Validate ``raw``; anything missing or malformed yields the unset state, never a default."""
    if not raw:
        return UNSET
    try:
        policy = RetentionPolicy.model_validate(dict(raw))
    except ValidationError:
        return PolicyState(status="unset", problem="invalid")
    return PolicyState(status="set", policy=policy)
