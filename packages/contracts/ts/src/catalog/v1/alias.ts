/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Alias document mapping an alias (external agent ID, label, previous ID) to one canonical ID; resolves collisions and agent aliases. Python validators: validate_canonical_id_fullmatch, validate_customer_segment_matches, validate_alias_type_matches (entity_type equals the type segment of canonical_id), validate_alias_unique (one active alias per (alias_source_id, alias_kind, alias_value)).
 */
export interface Alias {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Canonical ID of this alias document. Canonical ID (canonical_id.schema.json) whose type segment is 'alias'.
   */
  id: string;
  /**
   * Monotonic document version, incremented on every accepted write.
   */
  version: number;
  /**
   * Opaque optimistic-concurrency token. A mismatch on write returns the stale_version error.
   */
  etag: string;
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
   * Source-native identifier or label that resolves to canonical_id.
   */
  alias_value: string;
  alias_kind: "external_id" | "display_name" | "previous_canonical_id" | "source_native_id";
  /**
   * Source in which alias_value is valid.
   */
  alias_source_id: string;
  /**
   * Target canonical ID. Person aliases are forbidden: mapping a real identifier to a pseudonym is re-identification data and lives in the policy store.
   */
  canonical_id: string;
  entity_type:
    | "agent"
    | "agent_version"
    | "model_deployment"
    | "grounding_source"
    | "tool"
    | "service"
    | "domain"
    | "owner"
    | "policy"
    | "recommendation"
    | "run_reference";
  status: "active" | "retired";
  validity: Validity;
  provenance: Provenance;
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
