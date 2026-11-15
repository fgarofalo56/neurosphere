/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * One registered ingest producer (PRP-41). Carries every field of the ingest edge's ProducerRegistration (services/api ingest/auth.py) so the registry can be loaded from the admin_config store: the producer authenticates with Authorization: Bearer <producer_id>.<secret> and the edge compares SHA-256(secret) with secret_sha256 in constant time. Only the hash is stored; the secret is returned once, in ProducerSecretIssued. A disabled producer is refused at the edge. Rules JSON Schema cannot express (source_id values are unique) are checked by tests/contracts/validators.py::check_producer_sources_unique.
 */
export interface ProducerRecord {
  /**
   * Contract version of the document, major 1 with additive minor revisions (ADR-0004).
   */
  schema_version: string;
  /**
   * Producer identifier, the part of the bearer credential before the dot. Same grammar as ProducerRegistration.producer_id.
   */
  producer_id: string;
  /**
   * Customer segment of the canonical id grammar (the tenant deployment).
   */
  customer_id: string;
  /**
   * Azure cloud boundary. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Sources this producer may publish for, and how each source's data is observed (ProducerRegistration.sources).
   *
   * @minItems 1
   * @maxItems 64
   */
  sources: [ProducerSource, ...ProducerSource[]];
  /**
   * Lowercase hex SHA-256 of the producer secret. A digest, never the secret.
   */
  secret_sha256: string;
  status: "active" | "disabled";
  /**
   * When the current secret was issued (first issue or last rotation). Null for producers imported from a static registry file.
   */
  rotated_at: string | null;
}
/**
 * This interface was referenced by `ProducerRecord`'s JSON-Schema
 * via the `definition` "source".
 */
export interface ProducerSource {
  /**
   * Source identifier the producer publishes under (TelemetryEvent/CostRecord source_id).
   */
  source_id: string;
  observation_kind: "gateway" | "application" | "billing";
}
