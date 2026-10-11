/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Person as a pseudonymous principal only. There is deliberately no email, name, UPN, display_name, free-text or attributes field; re-identification is a policy-store concern, not a contract field. The id segment of the canonical ID is the pseudonym. Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at), validate_person_id_is_pseudonym (id segment equals principal_pseudonym).
 */
export interface Person {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Canonical ID whose id segment is the principal pseudonym (psn_...).
   */
  id: string;
  entity_type: "person";
  /**
   * Monotonic document version, incremented on every accepted write.
   */
  version: number;
  /**
   * Opaque optimistic-concurrency token. A mismatch on write returns the stale_version error.
   */
  etag: string;
  /**
   * Entity lifecycle state.
   */
  lifecycle_status: "draft" | "active" | "deprecated" | "retired";
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  created_at: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  updated_at: string;
  /**
   * Sovereign cloud boundary. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Customer segment of the canonical ID grammar.
   */
  customer_id: string;
  /**
   * Stable pseudonym produced by the pseudonymization service.
   */
  principal_pseudonym: string;
  /**
   * Pseudonymization scheme and key version, for rotation.
   */
  pseudonym_scheme: string;
  principal_kind?: "human" | "workload" | "unknown";
  /**
   * Home domain when known; people may act across domains.
   */
  domain_id?: string | null;
}
