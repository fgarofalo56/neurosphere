"""Argument models of the copilot tools.

Every model forbids extra keys and none has a scope, domain or customer field: scope comes from
the server-derived ``IdentityScope`` only. Read tools are built on the generated
``StructuredQuery`` (allowlisted fields and operators, mandatory budget); there is no free-text
query field anywhere.
"""

from __future__ import annotations

from typing import Annotated, Literal

from neurosphere_contracts.actions.v1.action_intent import EvidenceRef, ProposedDiff
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_contracts.query.v1.structured_query import StructuredQuery
from pydantic import BaseModel, ConfigDict, Field, StrictStr

__all__ = [
    "CostSummaryArgs",
    "EvidenceArgs",
    "ListRecommendationsArgs",
    "ProposeActionArgs",
    "SearchCatalogArgs",
    "ToolArgs",
]

EvidenceIdStr = Annotated[StrictStr, Field(min_length=1, max_length=256)]


class ToolArgs(BaseModel):
    """Base of every tool argument model."""

    model_config = ConfigDict(extra="forbid")

    def requested_budget(self) -> Budget | None:
        """The model-requested budget, clamped by the registry; ``None`` uses the server default."""
        return None


class SearchCatalogArgs(ToolArgs):
    query: StructuredQuery

    def requested_budget(self) -> Budget:
        return self.query.budget


class CostSummaryArgs(ToolArgs):
    query: StructuredQuery
    metric: Literal["cost", "latency", "errors"] = "cost"

    def requested_budget(self) -> Budget:
        return self.query.budget


class ListRecommendationsArgs(ToolArgs):
    query: StructuredQuery

    def requested_budget(self) -> Budget:
        return self.query.budget


class EvidenceArgs(ToolArgs):
    evidence_ids: Annotated[list[EvidenceIdStr], Field(min_length=1, max_length=50)]
    budget: Budget

    def requested_budget(self) -> Budget:
        return self.budget


class ProposeActionArgs(ToolArgs):
    """A change proposal. The domain is resolved server-side from the target entity."""

    action_kind: Annotated[StrictStr, Field(pattern="^[a-z][a-z0-9_]{0,63}$")]
    target: TargetRef
    target_version: Annotated[StrictStr, Field(min_length=1, max_length=256)]
    proposed_diff: ProposedDiff
    evidence: Annotated[list[EvidenceRef], Field(max_length=20)] = Field(
        default_factory=list[EvidenceRef]
    )
