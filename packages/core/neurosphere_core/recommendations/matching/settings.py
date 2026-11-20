"""``NS_MATCH_*`` settings of the agent/tool matcher.

=============================  =============================================================
``NS_MATCH_WEIGHTS``           JSON object signal name -> non-negative weight. Missing signals
                               get weight 0. Weights are renormalized over observed signals.
``NS_MATCH_CANDIDATE_CAP``     most candidates scored per call (default 200).
``NS_MATCH_FEEDBACK_BOUND``    largest absolute feedback prior (default 0.15).
``NS_MATCH_MIN_PRINCIPALS``    distinct principals needed before feedback counts (default 3).
``NS_MATCH_FEEDBACK_TTL_DAYS`` feedback retention in days (default 180).
=============================  =============================================================

The default weights are a starting point, not tuned values: nothing here has been calibrated
against real task outcomes, so treat scores as relative and revisit the weights with evidence.
"""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["DEFAULT_WEIGHTS", "SIGNAL_NAMES", "MatchSettings"]

SIGNAL_NAMES: tuple[str, ...] = (
    "capability_match",
    "tag_match",
    "text_match",
    "graph_proximity",
    "historical_success",
    "latency",
    "usage",
    "feedback_prior",
)

DEFAULT_WEIGHTS: dict[str, float] = {
    "capability_match": 0.25,
    "tag_match": 0.15,
    "text_match": 0.20,
    "graph_proximity": 0.10,
    "historical_success": 0.15,
    "latency": 0.05,
    "usage": 0.05,
    "feedback_prior": 0.05,
}


class MatchSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NS_MATCH_", frozen=True, extra="ignore")

    weights: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    candidate_cap: int = Field(default=200, ge=1, le=2000)
    feedback_bound: float = Field(default=0.15, ge=0.0, le=1.0)
    min_principals: int = Field(default=3, ge=1, le=100)
    feedback_ttl_days: int = Field(default=180, ge=1, le=3650)

    @field_validator("weights")
    @classmethod
    def _check_weights(cls, value: dict[str, float]) -> dict[str, float]:
        for name, weight in value.items():
            if name not in SIGNAL_NAMES:
                raise ValueError(f"unknown signal name: {name}")
            if weight < 0.0:
                raise ValueError(f"weight for {name} must be non-negative")
        return value
