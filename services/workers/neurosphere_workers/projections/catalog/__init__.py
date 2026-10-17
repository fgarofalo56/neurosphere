"""Catalog projection (PRP-10 item 3): outbox catalog sink -> inferred edges."""

from neurosphere_workers.projections.catalog.handler import (
    MAX_STALE_RETRIES,
    AliasModelResolver,
    CatalogProjection,
    DeterministicModelResolver,
    ModelDeploymentResolver,
    ProjectionStats,
)
from neurosphere_workers.projections.catalog.mapping import (
    CONFIDENCE_DELEGATION,
    CONFIDENCE_FAILED,
    CONFIDENCE_OK,
    INFERENCE_VERSION,
    EdgeCandidate,
    build_edge,
    delegation_candidate,
    deterministic_model_id,
    edge_id,
    model_call_candidate,
    tool_call_candidates,
)
from neurosphere_workers.projections.catalog.scope import (
    ClaimsSource,
    ScopeProvider,
    WorkloadScopeProvider,
)
from neurosphere_workers.projections.catalog.source import (
    InMemoryTraceEventSource,
    LoadedEvent,
    TraceEventSource,
)

__all__ = [
    "CONFIDENCE_DELEGATION",
    "CONFIDENCE_FAILED",
    "CONFIDENCE_OK",
    "INFERENCE_VERSION",
    "MAX_STALE_RETRIES",
    "AliasModelResolver",
    "CatalogProjection",
    "ClaimsSource",
    "DeterministicModelResolver",
    "EdgeCandidate",
    "InMemoryTraceEventSource",
    "LoadedEvent",
    "ModelDeploymentResolver",
    "ProjectionStats",
    "ScopeProvider",
    "TraceEventSource",
    "WorkloadScopeProvider",
    "build_edge",
    "delegation_candidate",
    "deterministic_model_id",
    "edge_id",
    "model_call_candidate",
    "tool_call_candidates",
]
