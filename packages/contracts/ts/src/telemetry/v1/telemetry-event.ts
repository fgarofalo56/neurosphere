/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * RFC 3339 timestamp in UTC (Z suffix).
 *
 * This interface was referenced by `TelemetryEvent`'s JSON-Schema
 * via the `definition` "timestamp".
 */
export type Timestamp = string;
/**
 * This interface was referenced by `TelemetryEvent`'s JSON-Schema
 * via the `definition` "identifier".
 */
export type Identifier = string;
/**
 * cloud:customer:source:type:id; lowercase [a-z0-9._-] segments, id may also contain / and =.
 *
 * This interface was referenced by `TelemetryEvent`'s JSON-Schema
 * via the `definition` "canonical_id".
 */
export type CanonicalId = string;
/**
 * This interface was referenced by `TelemetryEvent`'s JSON-Schema
 * via the `definition` "trace_id".
 */
export type TraceId = string;
/**
 * This interface was referenced by `TelemetryEvent`'s JSON-Schema
 * via the `definition` "span_id".
 */
export type SpanId = string;
/**
 * This interface was referenced by `TelemetryEvent`'s JSON-Schema
 * via the `definition` "label".
 */
export type Label = string;

/**
 * Normalized telemetry envelope for one observed span or event (NS-01). Raw telemetry lives outside the catalog graph. Missing values are null or the enumerated 'unknown', never 0 by default; numeric 0 is only ever a measured zero. Prompt and response bodies are never carried here; see payload_ref. Rules JSON Schema cannot express are enforced by Python validators in tests/contracts: validate_span_not_self_parent (span_id must differ from parent_span_id) and validate_canonical_id_grammar (canonical_agent_id must also pass the catalog canonical-ID grammar owned by schemas/catalog/v1).
 */
export interface TelemetryEvent {
  /**
   * Contract version of this document, major 1 with additive minor revisions.
   */
  schema_version: string;
  /**
   * Source-assigned event identifier. Idempotency is by (source_id, event_id).
   */
  event_id: string;
  /**
   * When the event happened at the source (RFC 3339 UTC).
   */
  event_time: string;
  /**
   * When the ingest edge accepted the event (RFC 3339 UTC). Stamped server-side; null on the producer wire before acceptance.
   */
  ingestion_time?: Timestamp | null;
  /**
   * Azure cloud boundary the event belongs to. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Customer (tenant deployment) identifier.
   */
  customer_id: string;
  /**
   * Owning domain identifier. Null when not yet attributed.
   */
  domain_id?: Identifier | null;
  /**
   * Connector or producer that emitted the event.
   */
  source_id: string;
  /**
   * Agent identifier as reported by the source system. Null when the source does not report one.
   */
  external_agent_id?: Identifier | null;
  /**
   * Resolved canonical agent ID (cloud:customer:source:type:id). Null until resolution succeeds. Pattern mirrors the catalog grammar; cross-checked by validate_canonical_id_grammar.
   */
  canonical_agent_id?: CanonicalId | null;
  /**
   * Request or correlation identifier from the source. Null when absent.
   */
  request_id?: Identifier | null;
  /**
   * W3C/OpenTelemetry trace ID, 32 lowercase hex characters. Null when the source is not traced.
   */
  trace_id?: TraceId | null;
  /**
   * W3C/OpenTelemetry span ID, 16 lowercase hex characters. Null when the source is not traced.
   */
  span_id?: SpanId | null;
  /**
   * Parent span ID; null for a root span or when unknown. Must differ from span_id (validate_span_not_self_parent).
   */
  parent_span_id?: SpanId | null;
  /**
   * What this span represents. delegation, tool_call, retry, error and cancellation are first-class so multi-agent call trees can be reconstructed.
   */
  span_kind?:
    | "request"
    | "agent_run"
    | "model_call"
    | "tool_call"
    | "delegation"
    | "retrieval"
    | "retry"
    | "error"
    | "cancellation"
    | "unknown";
  /**
   * 1-based attempt number for retry spans. Null when not a retry or not reported.
   */
  retry_attempt?: number | null;
  /**
   * Model or service provider (for example azure_openai). Null when unknown.
   */
  provider?: Label | null;
  /**
   * Model name as reported. Null when unknown.
   */
  model?: Label | null;
  /**
   * Model version as reported. Null when unknown.
   */
  model_version?: Label | null;
  /**
   * Deployment environment of the observed workload. 'sandbox' marks the isolated synthetic sandbox.
   */
  environment?: "production" | "staging" | "development" | "test" | "sandbox" | "unknown";
  /**
   * Result of the span.
   */
  outcome?: "success" | "error" | "cancelled" | "timeout" | "unknown";
  /**
   * Span duration in integer milliseconds. Null when not measured; 0 only when measured as zero.
   */
  duration_ms?: number | null;
  /**
   * Token counts. Null when the source reports no token usage at all.
   */
  token_breakdown?: TokenBreakdown | null;
  /**
   * Data sources touched by this span. Null when unknown; an empty array means observed to touch none.
   *
   * @maxItems 256
   */
  data_source_refs?: DataSourceRef[] | null;
  /**
   * Data classification label applied to the event (for example cui). Null when unclassified or unknown.
   */
  classification?: Label | null;
  /**
   * Sampling metadata. Null when the source does not report sampling.
   */
  sampling?: SamplingMetadata | null;
  /**
   * Optional pointer to a separately stored, redacted prompt/response payload. Bodies are off by default (NS-01).
   */
  payload_ref?: PayloadRef | null;
}
/**
 * Token counts for one model interaction. Each count is nullable and defaults to null: null means not reported, 0 means a measured zero. Also referenced by cost/v1/cost-record.schema.json.
 *
 * This interface was referenced by `TelemetryEvent`'s JSON-Schema
 * via the `definition` "token_breakdown".
 */
export interface TokenBreakdown {
  input?: number | null;
  output?: number | null;
  /**
   * Input tokens served from a provider prompt cache.
   */
  cached?: number | null;
  /**
   * Reasoning tokens reported separately by the provider.
   */
  reasoning?: number | null;
}
/**
 * Reference to a grounding source or data asset touched by the span.
 *
 * This interface was referenced by `TelemetryEvent`'s JSON-Schema
 * via the `definition` "data_source_ref".
 */
export interface DataSourceRef {
  /**
   * Canonical ID when resolved, otherwise the source-reported identifier.
   */
  ref: string;
  /**
   * Observed access mode.
   */
  access?: "read" | "write" | "unknown";
}
/**
 * This interface was referenced by `TelemetryEvent`'s JSON-Schema
 * via the `definition` "sampling".
 */
export interface SamplingMetadata {
  /**
   * Fraction of events retained, in [0, 1]; 1 means unsampled. Null when unknown.
   */
  rate?: number | null;
  /**
   * Sampling method.
   */
  method?: "none" | "head" | "tail" | "probabilistic" | "rate_limited" | "unknown";
  /**
   * Why this event was sampled or kept (for example error_kept). Null when not reported.
   */
  reason?: string | null;
}
/**
 * Pointer to a stored payload; never the payload itself. The pointer is opaque and is never fetched by schema validation.
 *
 * This interface was referenced by `TelemetryEvent`'s JSON-Schema
 * via the `definition` "payload_ref".
 */
export interface PayloadRef {
  /**
   * Opaque storage pointer (blob path or archive key).
   */
  pointer: string;
  /**
   * Classification label of the stored payload. Null when unknown.
   */
  classification?: string | null;
  /**
   * Redaction status of the stored payload.
   */
  redaction_state: "redacted" | "pending" | "redaction_failed" | "not_required" | "unknown";
}
