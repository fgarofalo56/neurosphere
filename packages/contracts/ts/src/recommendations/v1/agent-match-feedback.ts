/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Canonical ID grammar cloud:customer:source:type:id. cloud is commercial or government; customer, source and type are lowercase [a-z0-9._-]; id is lowercase [a-z0-9._-] plus '/' and '='; no segment may contain ':'. Corpus: id-corpus.json. Python validator validate_canonical_id_fullmatch re-checks with re.fullmatch because Python re.search lets '$' match before a trailing newline.
 */
export type CanonicalId = string;

/**
 * Stored feedback on one match candidate (PRP-70 item 3). It never carries task text: task_digest is the SHA-256 of the normalized task text. Reason codes only, no free text. Nullable fields are optional and default to null.
 */
export interface AgentMatchFeedback {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  feedback_id: string;
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
  match_id: string;
  entity_id: CanonicalId;
  entity_type: "agent" | "tool";
  decision: "accepted" | "rejected";
  reason_code?:
    | ("not_relevant" | "missing_capability" | "poor_quality" | "unavailable" | "policy" | "other")
    | null;
  rank_at_decision: number;
  score_at_decision: number;
  /**
   * SHA-256 of the normalized task text; the text itself is never stored.
   */
  task_digest: string;
  /**
   * @maxItems 16
   *
   * Items: Dot-namespaced capability token such as document.summarize (one to four segments). Open-ended: readers must tolerate unknown values. There is no closed taxonomy.
   */
  required_capabilities: string[];
  ranker: {
    /**
     * Lowercase identifier token (source IDs, platforms, providers, kinds).
     */
    ranker_id: string;
    ranker_version: string;
  };
  /**
   * Pseudonymous principal reference. Canonical ID (canonical_id.schema.json) whose type segment is 'person'.
   */
  decided_by: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  decided_at: string;
  expires_at?: string | null;
}
