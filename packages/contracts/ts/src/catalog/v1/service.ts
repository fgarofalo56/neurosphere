/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Service an agent or tool depends on (Azure service, SaaS, internal API, gateway). Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at).
 */
export interface Service {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Stable canonical ID of this entity. Canonical ID (canonical_id.schema.json) whose type segment is 'service'.
   */
  id: string;
  entity_type: "service";
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
   * Owning domain; authorization scope anchor. Canonical ID (canonical_id.schema.json) whose type segment is 'domain'.
   */
  domain_id: string;
  /**
   * Data classification label; unknown when not yet classified.
   */
  classification?: "public" | "internal" | "confidential" | "restricted" | "unknown";
  /**
   * Azure region holding the authoritative copy; null when unknown.
   */
  residency_region?: string | null;
  attributes?: Attributes;
  /**
   * Human-readable label for a non-person entity. Never a person's name.
   */
  display_name: string;
  service_kind?: "azure_service" | "saas" | "internal_api" | "gateway" | "other" | "unknown";
  /**
   * Lowercase identifier token (source IDs, platforms, providers, kinds).
   */
  source_id: string;
  azure_resource_type?: string | null;
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
