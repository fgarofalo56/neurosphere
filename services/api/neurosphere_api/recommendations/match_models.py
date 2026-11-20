"""Wire models for the agent and tool match routes (PRP-72 item 4).

The request, the feedback request and the response are the PRP-70 contract types, re-exported.
The contract has no per-candidate ``confidence`` and no metrics response, so this module adds:

* :class:`AgentMatchView` -- the contract response unchanged under ``match`` plus one
  :class:`CandidateAssessment` per returned candidate (``confidence`` and ``cold_start``).
  ``confidence`` is a relative 0-1 value built from the score, the share of weight that was
  observed and the margin to the next candidate. It is NOT a probability.
* :class:`MatchMetricsView` -- counts for a window; ``acceptance_rate`` is ``null`` (never 0) when
  there is no feedback.
* :class:`FeedbackAccepted` -- the 202 body of the feedback route.

No ``from __future__ import annotations``: FastAPI inspects these models.
"""

from datetime import datetime
from typing import Final, Literal

from neurosphere_contracts.recommendations.v1.agent_match_feedback_request import (
    AgentMatchFeedbackRequest,
)
from neurosphere_contracts.recommendations.v1.agent_match_request import AgentMatchRequest
from neurosphere_contracts.recommendations.v1.agent_match_response import AgentMatchResponse
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CONFIDENCE_NOTE",
    "AgentMatchFeedbackRequest",
    "AgentMatchRequest",
    "AgentMatchResponse",
    "AgentMatchView",
    "CandidateAssessment",
    "FeedbackAccepted",
    "MatchMetricsView",
]

CONFIDENCE_NOTE: Final = (
    "confidence is a relative 0-1 value derived from the score, the share of weight that was "
    "observed and the margin to the next candidate; it is not a probability"
)


class CandidateAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    """Relative, not a probability; capped for candidates without observed telemetry."""
    cold_start: bool
    """True when the candidate had no observed telemetry (its telemetry signals are unobserved)."""


class AgentMatchView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match: AgentMatchResponse
    assessments: list[CandidateAssessment]
    confidence_note: str = CONFIDENCE_NOTE


class FeedbackAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match_id: str
    entity_id: str
    decision: Literal["accepted", "rejected"]
    decided_at: datetime


class MatchMetricsView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain_id: str
    window_start: datetime
    window_end: datetime
    matches: int = Field(ge=0)
    matches_with_feedback: int = Field(ge=0)
    accepts: int = Field(ge=0)
    rejects: int = Field(ge=0)
    acceptance_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    """``accepts / (accepts + rejects)``; ``null`` (not 0) when there is no feedback."""
