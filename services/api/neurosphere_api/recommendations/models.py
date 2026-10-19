"""Wire models for the recommendations API (PRP-15 item 4).

``Recommendation`` is the PRP-01 generated document verbatim. Routes serialize with
``response_model_exclude_unset`` so optional absent fields stay absent and nullable fields
(``observed_fraction``, ``owner_id``) stay null: unknown is never rendered as 0.

No ``from __future__ import annotations``: FastAPI inspects these models.
"""

from typing import Final, Literal

from neurosphere_contracts.recommendations.v1.recommendation import Recommendation
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "EXECUTION_REFUSAL_REASON",
    "EXECUTION_REFUSAL_REASON_CODE",
    "ExecutionState",
    "RecommendationDetail",
    "RecommendationList",
    "ReviewRequestBody",
    "ReviewRequestCreated",
    "ReviewState",
]

EXECUTION_REFUSAL_REASON: Final = "action gates not passed"
EXECUTION_REFUSAL_REASON_CODE: Final = "action_gates_not_passed"


class RecommendationList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[Recommendation]
    next_cursor: str | None


class ReviewState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: Literal["not_routed", "pending_review"]
    review_request_id: str | None


class ExecutionState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executable: Literal[False] = False
    reason: str = EXECUTION_REFUSAL_REASON


class RecommendationDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation: Recommendation
    review: ReviewState
    execution: ExecutionState


class ReviewRequestBody(BaseModel):
    """Only the recommendation id is read; ``domain_id``/``customer_id`` in the body are ignored."""

    model_config = ConfigDict(extra="ignore")

    recommendation_id: str = Field(min_length=1, max_length=512)


class ReviewRequestCreated(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_request_id: str
    state: Literal["pending_review"]
