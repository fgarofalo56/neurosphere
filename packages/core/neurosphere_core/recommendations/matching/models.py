"""Internal frozen models of the matcher: one signal reading and one combined result."""

from __future__ import annotations

from typing import Annotated

from neurosphere_contracts.recommendations.v1.agent_match_response import AgentMatchSignal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr

__all__ = ["CombinedResult", "ProximityPath", "SignalValue"]

Unit = Annotated[StrictFloat, Field(ge=0.0, le=1.0)]


class ProximityPath(BaseModel):
    """One bounded-walk hit: the candidate is ``hops`` edges of ``edge_type`` from an anchor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    hops: Annotated[StrictInt, Field(ge=0, le=3)]
    edge_type: StrictStr


class SignalValue(BaseModel):
    """One signal reading for one candidate. ``value`` is None when unobserved, never 0."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    signal: StrictStr
    value: Unit | None
    detail_code: StrictStr | None = None
    matched: tuple[StrictStr, ...] = ()
    """Tokens that matched (tag and capability signals); empty otherwise."""
    edge_type: StrictStr | None = None
    hops: StrictInt | None = None
    """Relationship path kept for the proximity explanation."""


class CombinedResult(BaseModel):
    """Score plus its per-signal explanation. ``score`` is relative, not a probability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    score: Unit
    contributions: tuple[AgentMatchSignal, ...]
    signal_values: tuple[SignalValue, ...]
    cold_start: StrictBool
    confidence: Unit
    """A relative ordering aid derived from score, observed weight and margin; not a probability."""
    unobserved: tuple[StrictStr, ...]
    observed_share: Unit
    """Share of the configured weight that sat on observed signals."""
