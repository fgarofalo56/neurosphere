/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Steward decision on one edge (accept, reject, override, lock, unlock), applied with optimistic concurrency. The schema has no field that removes or replaces evidence_ids or security_evidence_ids, so an override cannot erase security evidence; observed facts are retained and the lock changes presented lineage only. lock and override decisions require a lock with locked=true, reason, expiry and actor. Python validators: validate_override_preserves_security_evidence, validate_customer_segment_matches, validate_override_relation_matches_edge (relation_type equals the type segment of edge_id), validate_lock_expiry_after_decision.
 */
export interface EdgeOverride {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Canonical ID of this immutable override decision. Canonical ID (canonical_id.schema.json) whose type segment is 'edge_override'.
   */
  id: string;
  /**
   * Edge being curated. Canonical ID (canonical_id.schema.json) whose type segment is 'invokes' or 'delegates_to' or 'uses_model' or 'reads' or 'writes' or 'grounded_by' or 'owned_by' or 'depends_on' or 'supersedes'.
   */
  edge_id: string;
  /**
   * Relation name in wire form (lowercase snake_case of INVOKES, DELEGATES_TO, USES_MODEL, READS, WRITES, GROUNDED_BY, OWNED_BY, DEPENDS_ON, SUPERSEDES).
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
    | "supersedes";
  /**
   * Monotonic document version, incremented on every accepted write.
   */
  expected_edge_version: number;
  /**
   * Opaque optimistic-concurrency token. A mismatch on write returns the stale_version error.
   */
  expected_edge_etag: string;
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
  decision: "accept" | "reject" | "override" | "lock" | "unlock";
  /**
   * Pseudonymous principal reference. Canonical ID (canonical_id.schema.json) whose type segment is 'person'.
   */
  actor: string;
  reason: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  decided_at: string;
  lock?: Lock | null;
  set_confidence?: number | null;
  set_validity?: Validity | null;
  /**
   * Evidence appended by the steward. Evidence can be added, never removed.
   *
   * @maxItems 1000
   *
   * Items: Reference to an evidence record (trace, span, access log, audit record or steward decision). A pointer, never the evidence payload.
   */
  add_evidence_ids?: string[];
  review_item_id?: string | null;
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
 * Validity interval. valid_to null means open-ended. Python validator validate_validity_interval enforces valid_from < valid_to.
 */
export interface Validity {
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  valid_from: string;
  valid_to?: string | null;
}
