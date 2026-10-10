/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * DELEGATES_TO relation. Source agent hands a task to a target (sub-)agent. Every edge carries provenance, evidence_ids, confidence, first/last observation, validity interval, status and lock. Only curated edges may be locked; a curated edge carries its curation decision. Python validators: validate_canonical_id_fullmatch, validate_customer_segment_matches, validate_observation_order (first_observed <= last_observed), validate_validity_interval, validate_security_evidence_subset (security_evidence_ids is a subset of evidence_ids), validate_override_preserves_security_evidence (a new edge version keeps every prior security_evidence_ids entry), validate_lock_expiry_after_decision.
 */
export interface DelegatesToRelation {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Stable canonical ID of this edge. Canonical ID (canonical_id.schema.json) whose type segment is 'delegates_to'.
   */
  id: string;
  relation_type: "delegates_to";
  /**
   * Monotonic document version, incremented on every accepted write.
   */
  version: number;
  /**
   * Opaque optimistic-concurrency token. A mismatch on write returns the stale_version error.
   */
  etag: string;
  /**
   * Edge source entity. Canonical ID (canonical_id.schema.json) whose type segment is 'agent' or 'agent_version'.
   */
  source_id: string;
  /**
   * Edge target entity. Canonical ID (canonical_id.schema.json) whose type segment is 'agent' or 'agent_version'.
   */
  target_id: string;
  /**
   * Sovereign cloud boundary. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Customer segment of the canonical ID grammar.
   */
  customer_id: string;
  /**
   * Owning domain; authorization scope anchor. Canonical ID (canonical_id.schema.json) whose type segment is 'domain'.
   */
  domain_id: string;
  provenance: Provenance;
  /**
   * Evidence references; must be non-empty when status is inferred.
   *
   * @maxItems 1000
   *
   * Items: Reference to an evidence record (trace, span, access log, audit record or steward decision). A pointer, never the evidence payload.
   */
  evidence_ids: string[];
  /**
   * Subset of evidence_ids that is security evidence. Overrides can never remove an entry (see edge_override.schema.json).
   *
   * @maxItems 1000
   *
   * Items: Reference to an evidence record (trace, span, access log, audit record or steward decision). A pointer, never the evidence payload.
   */
  security_evidence_ids: string[];
  confidence: number;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  first_observed: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  last_observed: string;
  validity: Validity;
  /**
   * asserted = declared by an authorized source; inferred = derived from telemetry or similarity; curated = accepted, overridden or locked by a domain steward.
   */
  status: "asserted" | "inferred" | "curated";
  lock: Lock;
  curation?: Curation | null;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  created_at: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  updated_at: string;
  attributes?: Attributes;
}
/**
 * Where an edge or alias came from.
 */
export interface Provenance {
  method:
    | "trace_observation"
    | "observed_access"
    | "declared"
    | "embedding_similarity"
    | "steward_curation"
    | "import"
    | "unknown";
  /**
   * Connector or source that produced the observation.
   */
  source_id: string;
  connector_version?: string | null;
  /**
   * Version of the inference rule or model when method is inferred.
   */
  inference_version?: string | null;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  recorded_at: string;
}
/**
 * Validity interval. valid_to null means open-ended. Python validator validate_validity_interval enforces valid_from < valid_to.
 */
export interface Validity {
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  valid_from: string;
  valid_to?: string | null;
}
/**
 * Steward lock. Locks change presented lineage, never retained observations; re-inference must respect them. A lock (locked=true) requires reason, expiry and actor. Python validator validate_lock_expiry_after_decision enforces expiry later than the decision time.
 */
export interface Lock {
  locked: boolean;
  reason?: string | null;
  expiry?: string | null;
  actor?: string | null;
}
/**
 * Latest steward decision on an edge (full history lives in the audit log).
 */
export interface Curation {
  decision: "accepted" | "rejected" | "overridden";
  /**
   * Pseudonymous principal reference. Canonical ID (canonical_id.schema.json) whose type segment is 'person'.
   */
  decided_by: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  decided_at: string;
  reason: string;
  override_id?: string | null;
  review_item_id?: string | null;
}
/**
 * Extension point: scalar values only (string, number, boolean, null); keys are lowercase snake_case. Nested objects and arrays are rejected.
 */
export interface Attributes {
  /**
   * This interface was referenced by `Attributes`'s JSON-Schema definition
   * via the `patternProperty` "^[a-z][a-z0-9_]{0,63}$".
   */
  [k: string]: string | number | boolean | null | undefined;
}
