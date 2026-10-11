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
    StrictFloat,
    StrictInt,
    StrictStr,
)


class Identifier(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=256, min_length=1)]


class Label(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(max_length=128, min_length=1)]


class Timestamp(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            pattern="^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:([0-5][0-9]|60)(\\.[0-9]{1,9})?Z$"
        ),
    ]
    """
    RFC 3339 timestamp in UTC (Z suffix).
    """


class CanonicalId(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+$",
        ),
    ]
    """
    cloud:customer:source:type:id; lowercase [a-z0-9._-] segments, id may also contain / and =.
    """


class TraceId(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[0-9a-f]{32}$")]


class SpanId(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[0-9a-f]{16}$")]


class TokenBreakdown(BaseModel):
    """
    Token counts for one model interaction. Each count is nullable and defaults to null: null means not reported, 0 means a measured zero. Also referenced by cost/v1/cost-record.schema.json.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    input: Annotated[StrictInt | None, Field(ge=0)] = None
    output: Annotated[StrictInt | None, Field(ge=0)] = None
    cached: Annotated[StrictInt | None, Field(ge=0)] = None
    """
    Input tokens served from a provider prompt cache.
    """
    reasoning: Annotated[StrictInt | None, Field(ge=0)] = None
    """
    Reasoning tokens reported separately by the provider.
    """


class DataSourceRef(BaseModel):
    """
    Reference to a grounding source or data asset touched by the span.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    ref: Annotated[StrictStr, Field(max_length=512, min_length=1)]
    """
    Canonical ID when resolved, otherwise the source-reported identifier.
    """
    access: Literal["read", "write", "unknown"] | None = "unknown"
    """
    Observed access mode.
    """


class SamplingMetadata(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    rate: Annotated[StrictFloat | None, Field(ge=0.0, le=1.0)] = None
    """
    Fraction of events retained, in [0, 1]; 1 means unsampled. Null when unknown.
    """
    method: Literal["none", "head", "tail", "probabilistic", "rate_limited", "unknown"] | None = (
        "unknown"
    )
    """
    Sampling method.
    """
    reason: Annotated[StrictStr | None, Field(max_length=256, min_length=1)] = None
    """
    Why this event was sampled or kept (for example error_kept). Null when not reported.
    """


class PayloadRef(BaseModel):
    """
    Pointer to a stored payload; never the payload itself. The pointer is opaque and is never fetched by schema validation.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    pointer: Annotated[StrictStr, Field(max_length=1024, min_length=1)]
    """
    Opaque storage pointer (blob path or archive key).
    """
    classification: Annotated[StrictStr | None, Field(max_length=128, min_length=1)] = None
    """
    Classification label of the stored payload. Null when unknown.
    """
    redaction_state: Literal["redacted", "pending", "redaction_failed", "not_required", "unknown"]
    """
    Redaction status of the stored payload.
    """


class TelemetryEvent(BaseModel):
    """
    Normalized telemetry envelope for one observed span or event (NS-01). Raw telemetry lives outside the catalog graph. Missing values are null or the enumerated 'unknown', never 0 by default; numeric 0 is only ever a measured zero. Prompt and response bodies are never carried here; see payload_ref. Rules JSON Schema cannot express are enforced by Python validators in tests/contracts: validate_span_not_self_parent (span_id must differ from parent_span_id) and validate_canonical_id_grammar (canonical_agent_id must also pass the catalog canonical-ID grammar owned by schemas/catalog/v1).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: Annotated[StrictStr, Field(pattern="^1\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$")]
    """
    Contract version of this document, major 1 with additive minor revisions.
    """
    event_id: Identifier
    """
    Source-assigned event identifier. Idempotency is by (source_id, event_id).
    """
    event_time: Timestamp
    """
    When the event happened at the source (RFC 3339 UTC).
    """
    ingestion_time: Timestamp | None = None
    """
    When the ingest edge accepted the event (RFC 3339 UTC). Stamped server-side; null on the producer wire before acceptance.
    """
    cloud: Literal["commercial", "government"]
    """
    Azure cloud boundary the event belongs to. Government data is never bridged to Commercial.
    """
    customer_id: Identifier
    """
    Customer (tenant deployment) identifier.
    """
    domain_id: Identifier | None = None
    """
    Owning domain identifier. Null when not yet attributed.
    """
    source_id: Identifier
    """
    Connector or producer that emitted the event.
    """
    external_agent_id: Identifier | None = None
    """
    Agent identifier as reported by the source system. Null when the source does not report one.
    """
    canonical_agent_id: CanonicalId | None = None
    """
    Resolved canonical agent ID (cloud:customer:source:type:id). Null until resolution succeeds. Pattern mirrors the catalog grammar; cross-checked by validate_canonical_id_grammar.
    """
    request_id: Identifier | None = None
    """
    Request or correlation identifier from the source. Null when absent.
    """
    trace_id: TraceId | None = None
    """
    W3C/OpenTelemetry trace ID, 32 lowercase hex characters. Null when the source is not traced.
    """
    span_id: SpanId | None = None
    """
    W3C/OpenTelemetry span ID, 16 lowercase hex characters. Null when the source is not traced.
    """
    parent_span_id: SpanId | None = None
    """
    Parent span ID; null for a root span or when unknown. Must differ from span_id (validate_span_not_self_parent).
    """
    span_kind: (
        Literal[
            "request",
            "agent_run",
            "model_call",
            "tool_call",
            "delegation",
            "retrieval",
            "retry",
            "error",
            "cancellation",
            "unknown",
        ]
        | None
    ) = "unknown"
    """
    What this span represents. delegation, tool_call, retry, error and cancellation are first-class so multi-agent call trees can be reconstructed.
    """
    retry_attempt: Annotated[StrictInt | None, Field(ge=1)] = None
    """
    1-based attempt number for retry spans. Null when not a retry or not reported.
    """
    provider: Label | None = None
    """
    Model or service provider (for example azure_openai). Null when unknown.
    """
    model: Label | None = None
    """
    Model name as reported. Null when unknown.
    """
    model_version: Label | None = None
    """
    Model version as reported. Null when unknown.
    """
    environment: (
        Literal["production", "staging", "development", "test", "sandbox", "unknown"] | None
    ) = "unknown"
    """
    Deployment environment of the observed workload. 'sandbox' marks the isolated synthetic sandbox.
    """
    outcome: Literal["success", "error", "cancelled", "timeout", "unknown"] | None = "unknown"
    """
    Result of the span.
    """
    duration_ms: Annotated[StrictInt | None, Field(ge=0)] = None
    """
    Span duration in integer milliseconds. Null when not measured; 0 only when measured as zero.
    """
    token_breakdown: TokenBreakdown | None = None
    """
    Token counts. Null when the source reports no token usage at all.
    """
    data_source_refs: Annotated[list[DataSourceRef] | None, Field(max_length=256)] = None
    """
    Data sources touched by this span. Null when unknown; an empty array means observed to touch none.
    """
    classification: Label | None = None
    """
    Data classification label applied to the event (for example cui). Null when unclassified or unknown.
    """
    sampling: SamplingMetadata | None = None
    """
    Sampling metadata. Null when the source does not report sampling.
    """
    payload_ref: PayloadRef | None = None
    """
    Optional pointer to a separately stored, redacted prompt/response payload. Bodies are off by default (NS-01).
    """
