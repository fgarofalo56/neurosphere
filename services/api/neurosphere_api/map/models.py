"""Response models for the viewport wire contract (PRP-18 "Wire contract", Viewport).

Unknown metrics are ``null``, never 0. ``health`` is ``unknown`` unless a source states
otherwise. People are only ever shown by pseudonym: ``label`` of a ``person`` node is the
pseudonym and no field of this contract carries a real name.

No ``from __future__ import annotations``: FastAPI and pydantic resolve these annotations at
import time.
"""

from typing import Literal

from neurosphere_contracts.map.v1.map_node_facets import MapNodeFacets
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Coverage",
    "CoverageState",
    "Health",
    "ImpactBudget",
    "ImpactLevel",
    "ImpactNode",
    "ImpactRequest",
    "ImpactResponse",
    "NodeKind",
    "NodeMetrics",
    "Provenance",
    "SearchCounts",
    "SearchMatch",
    "SearchResponse",
    "TruncationReason",
    "ViewportEdge",
    "ViewportFilters",
    "ViewportNode",
    "ViewportResponse",
]

NodeKind = Literal[
    "person", "agent", "sub_agent", "model", "source", "service", "tool", "mcp_server", "cluster"
]
Health = Literal["ok", "degraded", "failing", "unknown"]
Provenance = Literal["observed", "declared", "inferred"]
CoverageState = Literal["complete", "partial", "delayed", "unknown"]
TruncationReason = Literal[
    "node_budget", "edge_budget", "scan_limit", "traversal_incomplete", "timeout_ms"
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NodeMetrics(_Model):
    tokens: float | None = None
    context_size: int | None = None
    frequency: float | None = None
    latency_p95_ms: float | None = None
    health: Health = "unknown"


class ViewportNode(_Model):
    id: str
    kind: NodeKind
    label: str
    cluster_id: str | None = None
    member_count: int | None = Field(default=None, ge=0)
    metrics: NodeMetrics = Field(default_factory=NodeMetrics)
    facets: MapNodeFacets | None = None
    health_inferred: bool = False
    """True when ``metrics.health`` and ``facets.health`` come from the dependents fallback rule
    (PRP-74 clarification 5), not from a measured subject point. Never ``ok`` when inferred."""


class ViewportEdge(_Model):
    id: str
    source: str
    target: str
    provenance: Provenance
    last_observed_at: str | None = None


class Coverage(_Model):
    state: CoverageState
    lag_seconds: float | None = None
    as_of: str | None = None


class ViewportFilters(_Model):
    """The filters a response was built with (PRP-74 item 2); each list is empty when unused."""

    node_type: list[str] = Field(default_factory=list)
    tag: list[str] = Field(default_factory=list)
    environment: list[str] = Field(default_factory=list)
    cloud: list[str] = Field(default_factory=list)
    health: list[str] = Field(default_factory=list)


class ViewportResponse(_Model):
    domain_id: str
    nodes: list[ViewportNode]
    edges: list[ViewportEdge]
    truncated: bool
    truncation_reason: TruncationReason | None = None
    next_cursor: str | None = None
    coverage: Coverage
    filters_applied: ViewportFilters | None = None
    """Set only when at least one filter was given; ``null`` means the unfiltered view."""


class ImpactBudget(_Model):
    """A request budget; it can only lower the server ceilings, never raise them."""

    max_accessors: int | None = Field(default=None, ge=1)
    timeout_ms: int | None = Field(default=None, ge=1)


class ImpactRequest(_Model):
    """Body of ``POST /domains/{domain_id}/impact`` (PRP-74 item 3)."""

    node_id: str = Field(min_length=1, max_length=512)
    max_depth: int = Field(default=3, ge=1, le=5)
    budget: ImpactBudget | None = None


class ImpactNode(_Model):
    """A dependent of the failing node. People are only ever the pseudonym (id and label)."""

    id: str
    kind: NodeKind
    label: str
    domain_id: str
    health: Health = "unknown"
    health_inferred: bool = False
    """True when ``health`` is the dependents fallback rule, not a measured subject point."""


class ImpactLevel(_Model):
    depth: int = Field(ge=1)
    nodes: list[ImpactNode]
    edge_ids: list[str]


class ImpactResponse(_Model):
    """Dependents of ``node_id`` (what relies on it), grouped by distance."""

    domain_id: str
    node_id: str
    direction: Literal["dependents"] = "dependents"
    levels: list[ImpactLevel]
    truncated: bool
    truncation_reason: TruncationReason | None = None
    coverage: Coverage


class SearchMatch(_Model):
    node: ViewportNode
    cluster_id: str
    """The cluster (``kind:<entity_type>``) that holds this node when the viewport is clustered."""


class SearchCounts(_Model):
    """Counts over ALL matches scanned (not only the returned page); each sums to the total."""

    by_kind: dict[str, int] = Field(default_factory=dict)
    by_health: dict[str, int] = Field(default_factory=dict)
    by_environment: dict[str, int] = Field(default_factory=dict)
    by_cloud: dict[str, int] = Field(default_factory=dict)


class SearchResponse(_Model):
    domain_id: str
    matches: list[SearchMatch]
    counts: SearchCounts
    truncated: bool
    truncation_reason: TruncationReason | None = None
    coverage: Coverage
    filters_applied: ViewportFilters | None = None
