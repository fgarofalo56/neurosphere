"""Narrow read ports the copilot tools depend on.

Each port exposes only what a tool needs, so a tool cannot reach a write path by construction.
The existing core services satisfy them structurally (``CatalogRepository``,
``AggregateReader``, ``RecommendationStore``); evidence and action drafting are bound by the
orchestrator. ``ActionDrafter`` has exactly one method, ``draft``: the copilot can create a draft
intent and nothing else (no confirm, no execute).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol

from neurosphere_contracts.actions.v1.action_intent import ActionIntent
from neurosphere_contracts.recommendations.v1.recommendation import Recommendation
from pydantic import BaseModel, ConfigDict, Field

from neurosphere_core.actions import DraftRequest
from neurosphere_core.aggregates import AggregateWindow, Grain, Metric, QueryResult
from neurosphere_core.catalog import CatalogEntity, EntityFilter
from neurosphere_core.paging import Page, PageRequest
from neurosphere_core.scope import IdentityScope

__all__ = [
    "ActionDrafter",
    "CatalogReader",
    "EvidenceReader",
    "EvidenceRecord",
    "MetricsReader",
    "RecommendationReader",
]

EvidenceKind = Literal[
    "recommendation",
    "evaluation_result",
    "telemetry_query",
    "cost_record",
    "catalog_entity",
    "policy",
    "document",
]


class EvidenceRecord(BaseModel):
    """A pointer to evidence (never an inline body) in one domain."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(min_length=1, max_length=256)
    kind: EvidenceKind
    ref: str = Field(min_length=1, max_length=512)
    domain_id: str
    observed_at: str | None


class CatalogReader(Protocol):
    async def get_entity(self, scope: IdentityScope, entity_id: str) -> CatalogEntity | None: ...

    async def list_entities(
        self, scope: IdentityScope, flt: EntityFilter, page: PageRequest
    ) -> Page[CatalogEntity]: ...


class MetricsReader(Protocol):
    async def query(
        self,
        customer_id: str,
        domain_id: str,
        metric: Metric,
        grain: Grain,
        window: AggregateWindow,
        *,
        max_series: int,
        max_points: int,
    ) -> QueryResult: ...


class RecommendationReader(Protocol):
    async def list(
        self,
        scope: IdentityScope,
        domain: str,
        kind: str | None = None,
        q: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Page[Recommendation]: ...


class EvidenceReader(Protocol):
    async def get_many(
        self, scope: IdentityScope, domain_ids: Sequence[str], evidence_ids: Sequence[str]
    ) -> Sequence[EvidenceRecord]:
        """Evidence records among ``evidence_ids`` that live in ``domain_ids`` (server-derived)."""
        ...


class ActionDrafter(Protocol):
    """Creates a ``drafted`` ActionIntent through the PRP-17 action service. Draft only."""

    async def draft(
        self, scope: IdentityScope, request: DraftRequest, *, domain_id: str
    ) -> ActionIntent: ...
