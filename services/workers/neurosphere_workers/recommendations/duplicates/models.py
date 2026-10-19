"""Result models and the optional signal-provider hook of the duplicate-candidate job."""

from __future__ import annotations

from typing import Annotated, Any, Protocol

from neurosphere_contracts.recommendations.v1.recommendation import Recommendation
from neurosphere_core.catalog.protocol import EntityFilter
from neurosphere_core.paging import Page, PageRequest
from neurosphere_core.scope import IdentityScope
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr

Unit = Annotated[StrictFloat, Field(ge=0.0, le=1.0)]


class AgentLister(Protocol):
    """The one read the job needs beyond ``GraphQuery``: list agents inside a scope.

    ``GraphQuery`` has no listing operation. Any ``CatalogRepository`` satisfies this
    structurally; the job never sees (or imports) the repository's write methods.
    """

    async def list_entities(
        self, scope: IdentityScope, flt: EntityFilter, page: PageRequest
    ) -> Page[Any]: ...


class SimilaritySignalProvider(Protocol):
    """Optional extra signal (for example embedding cosine similarity). Default: none.

    ``similarity`` returns a value in [0, 1], or ``None`` when the provider has no vector for
    one of the agents (the signal is then unobserved for that pair, widening its bounds).
    The provider is only ever asked about agents that are already inside the caller's scope.
    """

    def similarity(self, agent_a: str, agent_b: str) -> float | None: ...


class SignalBreakdown(BaseModel):
    """Per-candidate explanation of the similarity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    shared_source_ids: tuple[StrictStr, ...]
    shared_model_deployment_ids: tuple[StrictStr, ...]
    shared_tool_ids: tuple[StrictStr, ...]
    grounding_sources: Unit
    model_deployment: Unit
    tools: Unit
    shared_owner_ids: tuple[StrictStr, ...]
    owner: Unit
    agent_kind: Unit
    """1.0 when both agents have the same ``agent_kind``."""
    embedding: Unit | None
    """None when no provider is configured or it had no value for the pair."""
    same_domain_id: StrictStr
    """Pairs are only formed inside one domain, so this is the shared domain."""
    unobserved_signals: tuple[StrictStr, ...]
    corroborating_signals: StrictInt


class DuplicateCandidate(BaseModel):
    """A pair at or above ``min_similarity``: the advisory record plus its breakdown."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    recommendation: Recommendation
    breakdown: SignalBreakdown


class ReviewCandidate(BaseModel):
    """A pair between ``review_floor`` and ``min_similarity``: surfaced for a human to look
    at, but NOT a recommendation and never routed anywhere automatically."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    subject_ids: tuple[StrictStr, StrictStr]
    domain_id: StrictStr
    similarity: Unit
    breakdown: SignalBreakdown


class DuplicateRun(BaseModel):
    """Everything one job run produced, with its bounds stated."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidates: tuple[DuplicateCandidate, ...]
    review_candidates: tuple[ReviewCandidate, ...]
    truncated: StrictBool
    """True when a bound (agents, pairs compared, candidates returned, per-agent edges)
    stopped the job early; the output is then partial and must be labelled as such."""
    truncation_reasons: tuple[StrictStr, ...]
    agents_considered: StrictInt
    pairs_compared: StrictInt
    generator_id: StrictStr
    generator_version: StrictStr
