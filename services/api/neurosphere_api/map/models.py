"""Response models for the viewport wire contract (PRP-18 "Wire contract", Viewport).

Unknown metrics are ``null``, never 0. ``health`` is ``unknown`` unless a source states
otherwise. People are only ever shown by pseudonym: ``label`` of a ``person`` node is the
pseudonym and no field of this contract carries a real name.

No ``from __future__ import annotations``: FastAPI and pydantic resolve these annotations at
import time.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Coverage",
    "CoverageState",
    "Health",
    "NodeKind",
    "NodeMetrics",
    "Provenance",
    "TruncationReason",
    "ViewportEdge",
    "ViewportNode",
    "ViewportResponse",
]

NodeKind = Literal["person", "agent", "sub_agent", "model", "source", "cluster"]
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


class ViewportResponse(_Model):
    domain_id: str
    nodes: list[ViewportNode]
    edges: list[ViewportEdge]
    truncated: bool
    truncation_reason: TruncationReason | None = None
    next_cursor: str | None = None
    coverage: Coverage
