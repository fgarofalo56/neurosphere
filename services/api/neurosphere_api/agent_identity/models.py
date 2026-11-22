"""Request and response models of the agent identity API (PRP-137 item 5).

Defined here, not taken from core or contracts: a model used as ``response_model`` that lives in a
shared package renames ``openapi.json`` components. ``reason`` is a reason CODE (not free text) so
an audit record can carry it without carrying anything a person typed.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "RERESOLVE_COMMAND",
    "AliasDeclareRequest",
    "AliasDeclareView",
    "AliasView",
    "ReresolveJob",
]

#: The operator job that applies an alias change to events already processed (item 4).
RERESOLVE_COMMAND: Final = "python -m neurosphere_workers.agent_identity reresolve"
_CODE: Final = r"^[a-z][a-z0-9_]{0,63}$"

Outcome = Literal["created", "repointed", "unchanged"]


class AliasDeclareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=128)
    external_agent_id: str = Field(min_length=1, max_length=512)
    target_agent_id: str = Field(min_length=1, max_length=512)
    reason: str | None = Field(default=None, pattern=_CODE)


class ReresolveJob(BaseModel):
    """The exact operator command; arguments are separate so they can be passed without a shell."""

    model_config = ConfigDict(extra="forbid")

    command: str
    arguments: list[str]


class AliasDeclareView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Outcome
    alias_id: str | None
    retired_alias_id: str | None
    target_agent_id: str
    reresolve_needed: bool
    reresolve_job: ReresolveJob | None


class AliasView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    external_agent_id: str
    target_agent_id: str
