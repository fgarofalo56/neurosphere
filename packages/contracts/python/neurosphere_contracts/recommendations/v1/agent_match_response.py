# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
)

from ...catalog.v1 import common


class OpaqueId(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[a-z0-9][a-z0-9._:/=-]{0,255}$")]


class SignalName(
    RootModel[
        Literal[
            "capability_match",
            "tag_match",
            "text_match",
            "graph_proximity",
            "historical_success",
            "latency",
            "usage",
            "feedback_prior",
        ]
    ]
):
    root: Literal[
        "capability_match",
        "tag_match",
        "text_match",
        "graph_proximity",
        "historical_success",
        "latency",
        "usage",
        "feedback_prior",
    ]


class Value(RootModel[StrictFloat]):
    root: Annotated[StrictFloat, Field(ge=0.0, le=1.0)] = None
    """
    Normalized signal value in [0,1]; null means unknown, never 0.
    """


class Ranker(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    ranker_id: common.Token
    ranker_version: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9._+-]{1,64}$")]


class AgentMatchSignal(BaseModel):
    """
    One ranking signal. value null means unknown (never 0); weight is the signal's weight in the ranker; contribution is its signed share of the score.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    signal: SignalName
    value: Value | None = None
    """
    Normalized signal value in [0,1]; null means unknown, never 0.
    """
    weight: Annotated[StrictFloat, Field(ge=0.0, le=1.0)]
    contribution: Annotated[StrictFloat, Field(ge=-1.0, le=1.0)]
    detail_code: common.Token | None = None
    """
    Machine-readable detail; null when none.
    """
    evidence_ids: Annotated[
        list[common.EvidenceId] | None, Field(max_length=20, validate_default=True)
    ] = []


class Relation(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    relation_type: common.RelationType
    entity_id: common.CanonicalId
    direction: Literal["outgoing", "incoming"]


class AgentMatchCandidate(BaseModel):
    """
    One ranked candidate. score is a relative weighted score in [0,1], not a probability. signals is required so every ranking is explainable.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    rank: Annotated[StrictInt, Field(ge=1, le=50)]
    entity_id: common.CanonicalId
    entity_type: Literal["agent", "tool"]
    display_name: common.DisplayName
    lifecycle_status: common.LifecycleStatus
    score: Annotated[StrictFloat, Field(ge=0.0, le=1.0)]
    """
    Relative weighted score in [0,1]; not a probability.
    """
    signals: Annotated[list[AgentMatchSignal], Field(max_length=8)]
    matched_capabilities: Annotated[list[common.Capability], Field(max_length=16)]
    matched_tags: Annotated[list[common.Tag], Field(max_length=16)]
    relations: Annotated[list[Relation], Field(max_length=20)]
    evidence_ids: Annotated[list[common.EvidenceId], Field(max_length=50)]


class AgentMatchResponse(BaseModel):
    """
    Ranked task-to-agent candidates (PRP-70 item 3). The explanation is a structured per-signal breakdown plus related entity ids; no model-written free text. score is a relative weighted score, not a probability. Unknown signal values are null, never 0. cold_start is true when history-based signals are unavailable; those signals are named in signals_unavailable.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    match_id: OpaqueId
    domain_id: common.DomainId
    generated_at: common.Timestamp
    ranker: Ranker
    cold_start: StrictBool
    signals_unavailable: Annotated[list[SignalName], Field(max_length=8)]
    """
    Signals that could not be computed for this response.
    """
    candidates: Annotated[list[AgentMatchCandidate], Field(max_length=50)]
    truncated: StrictBool
    partial_reason: Literal["limit", "timeout_ms"] | None = None
    """
    Why the result is partial; null when complete.
    """
