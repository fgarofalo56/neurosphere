"""Versioned configuration of the duplicate-candidate job (PRP-15 item 2).

Frozen, ``extra="forbid"``: a recommendation cites ``generator_id`` + ``version`` of the
config that produced it, so a config can never change underneath a published record.
"""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

GENERATOR_ID = "duplicates.shared-relations"
"""Matches the contract's ``opaque_id`` pattern (lowercase)."""

Weight = Annotated[StrictFloat, Field(ge=0.0, le=1.0)]


class SignalWeights(BaseModel):
    """Relative weights of the similarity signals.

    Only weights of signals that are *active* for a pair take part in the normalisation:
    ``embedding`` counts only when a signal provider is plugged in. Same-domain is a gate
    (pairs are only formed inside one domain), not a weighted signal.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    grounding_sources: Weight = 0.30
    model_deployment: Weight = 0.20
    tools: Weight = 0.25
    owner: Weight = 0.15
    agent_kind: Weight = 0.10
    embedding: Weight = 0.15

    @model_validator(mode="after")
    def _some_baseline_weight(self) -> Self:
        if self.grounding_sources + self.model_deployment + self.tools <= 0.0:
            raise ValueError("at least one relation-based signal needs a positive weight")
        return self


class DuplicateConfig(BaseModel):
    """Thresholds, weights and bounds of one generator version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    generator_id: Annotated[StrictStr, Field(pattern=r"^[a-z0-9][a-z0-9._:/=-]{0,255}$")] = (
        GENERATOR_ID
    )
    version: Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9._+-]{1,64}$")] = "1.0.0"
    weights: SignalWeights = SignalWeights()

    min_similarity: Annotated[StrictFloat, Field(gt=0.0, le=1.0)] = 0.9
    """At or above: emitted as a ``candidate_duplicate`` recommendation."""
    review_floor: Annotated[StrictFloat, Field(ge=0.0, lt=1.0)] = 0.7
    """At or above this but below ``min_similarity``: returned as a review candidate only."""
    inferred_edge_weight: Annotated[StrictFloat, Field(ge=0.0, le=1.0)] = 0.25
    """Multiplier on the confidence of trace-INFERRED relations. Two agents that are copies
    of each other are declared alike; inferred edges only reflect which paths a limited
    trace sample happened to exercise, so they count for less than asserted or curated
    ones. 0 ignores inferred relations; 1 trusts them like declared ones."""
    min_observed_fraction: Annotated[StrictFloat, Field(ge=0.0, le=1.0)] = 0.6
    """Share of the total signal weight that must be observable for a pair (for example a
    model deployment homed in a domain outside the caller's scope leaves that signal
    unobserved). Thinner evidence is not scored."""
    min_shared_sources: Annotated[StrictInt, Field(ge=0, le=100)] = 2
    """Grounding sources both agents must share. One shared knowledge base is common in a
    domain and says little; two or more is the consolidation-review signal. 0 disables."""
    min_corroborating_signals: Annotated[StrictInt, Field(ge=1, le=5)] = 2
    """A pair needs at least this many independent signals with a non-zero value; one
    coincidental overlap (for example a single popular source) never qualifies."""

    max_agents: Annotated[StrictInt, Field(ge=2, le=100_000)] = 5_000
    max_pairs_compared: Annotated[StrictInt, Field(ge=1, le=10_000_000)] = 200_000
    max_candidates: Annotated[StrictInt, Field(ge=1, le=10_000)] = 500
    """Cap applied to recommendations and, separately, to review candidates."""
    max_edges_per_agent: Annotated[StrictInt, Field(ge=1, le=1000)] = 200
    neighbor_timeout_ms: Annotated[StrictInt, Field(ge=1, le=30_000)] = 5_000

    @model_validator(mode="after")
    def _floor_below_threshold(self) -> Self:
        if self.review_floor >= self.min_similarity:
            raise ValueError("review_floor must be below min_similarity")
        return self
