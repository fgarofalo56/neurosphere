/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * This interface was referenced by `AgentMatchResponse`'s JSON-Schema
 * via the `definition` "opaque_id".
 */
export type OpaqueId = string;
/**
 * This interface was referenced by `AgentMatchResponse`'s JSON-Schema
 * via the `definition` "signal_name".
 */
export type SignalName =
  | "capability_match"
  | "tag_match"
  | "text_match"
  | "graph_proximity"
  | "historical_success"
  | "latency"
  | "usage"
  | "feedback_prior";
/**
 * Canonical ID grammar cloud:customer:source:type:id. cloud is commercial or government; customer, source and type are lowercase [a-z0-9._-]; id is lowercase [a-z0-9._-] plus '/' and '='; no segment may contain ':'. Corpus: id-corpus.json. Python validator validate_canonical_id_fullmatch re-checks with re.fullmatch because Python re.search lets '$' match before a trailing newline.
 */
export type CanonicalId = string;

/**
 * Ranked task-to-agent candidates (PRP-70 item 3). The explanation is a structured per-signal breakdown plus related entity ids; no model-written free text. score is a relative weighted score, not a probability. Unknown signal values are null, never 0. cold_start is true when history-based signals are unavailable; those signals are named in signals_unavailable.
 */
export interface AgentMatchResponse {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  match_id: OpaqueId;
  /**
   * Owning domain; authorization scope anchor. Canonical ID (canonical_id.schema.json) whose type segment is 'domain'.
   */
  domain_id: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  generated_at: string;
  ranker: Ranker;
  cold_start: boolean;
  /**
   * Signals that could not be computed for this response.
   *
   * @maxItems 8
   */
  signals_unavailable: SignalName[];
  /**
   * @maxItems 50
   */
  candidates: AgentMatchCandidate[];
  truncated: boolean;
  /**
   * Why the result is partial; null when complete.
   */
  partial_reason?: ("limit" | "timeout_ms") | null;
}
/**
 * This interface was referenced by `AgentMatchResponse`'s JSON-Schema
 * via the `definition` "ranker".
 */
export interface Ranker {
  /**
   * Lowercase identifier token (source IDs, platforms, providers, kinds).
   */
  ranker_id: string;
  ranker_version: string;
}
/**
 * One ranked candidate. score is a relative weighted score in [0,1], not a probability. signals is required so every ranking is explainable.
 *
 * This interface was referenced by `AgentMatchResponse`'s JSON-Schema
 * via the `definition` "candidate".
 */
export interface AgentMatchCandidate {
  rank: number;
  entity_id: CanonicalId;
  entity_type: "agent" | "tool";
  /**
   * Human-readable label for a non-person entity. Never a person's name.
   */
  display_name: string;
  /**
   * Entity lifecycle state.
   */
  lifecycle_status: "draft" | "active" | "deprecated" | "retired";
  /**
   * Relative weighted score in [0,1]; not a probability.
   */
  score: number;
  /**
   * @maxItems 8
   */
  signals: AgentMatchSignal[];
  /**
   * @maxItems 16
   *
   * Items: Dot-namespaced capability token such as document.summarize (one to four segments). Open-ended: readers must tolerate unknown values. There is no closed taxonomy.
   */
  matched_capabilities: string[];
  /**
   * @maxItems 16
   *
   * Items: Lowercase label token used for grouping and filtering catalog entities.
   */
  matched_tags: string[];
  /**
   * @maxItems 20
   */
  relations: Relation[];
  /**
   * @maxItems 50
   *
   * Items: Reference to an evidence record (trace, span, access log, audit record or steward decision). A pointer, never the evidence payload.
   */
  evidence_ids: string[];
}
/**
 * One ranking signal. value null means unknown (never 0); weight is the signal's weight in the ranker; contribution is its signed share of the score.
 *
 * This interface was referenced by `AgentMatchResponse`'s JSON-Schema
 * via the `definition` "signal".
 */
export interface AgentMatchSignal {
  signal: SignalName;
  /**
   * Normalized signal value in [0,1]; null means unknown, never 0.
   */
  value?: number | null;
  weight: number;
  contribution: number;
  /**
   * Machine-readable detail; null when none.
   */
  detail_code?: string | null;
  /**
   * @maxItems 20
   *
   * Items: Reference to an evidence record (trace, span, access log, audit record or steward decision). A pointer, never the evidence payload.
   */
  evidence_ids?: string[];
}
/**
 * This interface was referenced by `AgentMatchResponse`'s JSON-Schema
 * via the `definition` "relation".
 */
export interface Relation {
  /**
   * Relation name in wire form (lowercase snake_case of INVOKES, DELEGATES_TO, USES_MODEL, READS, WRITES, GROUNDED_BY, OWNED_BY, DEPENDS_ON, SUPERSEDES, GRANTS_ACCESS_TO).
   */
  relation_type:
    | "invokes"
    | "delegates_to"
    | "uses_model"
    | "reads"
    | "writes"
    | "grounded_by"
    | "owned_by"
    | "depends_on"
    | "supersedes"
    | "grants_access_to";
  entity_id: CanonicalId;
  direction: "outgoing" | "incoming";
}
