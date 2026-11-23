/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Free-form lowercase labels; at most 32, no duplicates.
 *
 * @maxItems 32
 *
 * Items: Lowercase label token used for grouping and filtering catalog entities.
 */
export type Tags = string[];
/**
 * Declared capabilities; at most 64, no duplicates.
 *
 * @maxItems 64
 *
 * Items: Dot-namespaced capability token such as document.summarize (one to four segments). Open-ended: readers must tolerate unknown values. There is no closed taxonomy.
 */
export type Capabilities = string[];
/**
 * Approval state of an agent version. Open-ended: readers must tolerate unknown values.
 */
export type AgentVersionApprovalState =
  "not_required" | "pending" | "approved" | "rejected" | "suspended";

/**
 * Immutable release of an Agent (instructions, tools and model bindings at a point in time). Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at).
 */
export interface AgentVersion {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Stable canonical ID of this entity. Canonical ID (canonical_id.schema.json) whose type segment is 'agent_version'.
   */
  id: string;
  entity_type: "agent_version";
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
   * Parent Agent. Canonical ID (canonical_id.schema.json) whose type segment is 'agent'.
   */
  agent_id: string;
  version_label: string;
  released_at?: string | null;
  /**
   * Hash of the version's declarative configuration.
   */
  config_hash?: string | null;
  tags?: Tags;
  capabilities?: Capabilities;
  /**
   * Declared Semantic Version of this release; null when not declared (version_label stays the free-form label).
   */
  semver?: string | null;
  /**
   * Approval record; null when no approval was recorded.
   */
  approval?: AgentVersionApproval | null;
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
/**
 * Approval record of one agent version (PRP-99). Null on AgentVersion means no approval was recorded.
 */
export interface AgentVersionApproval {
  state: AgentVersionApprovalState;
  requested_at?: string | null;
  decided_at?: string | null;
  decided_by?: string | null;
  /**
   * Action intent that made the decision (lowercase UUID).
   */
  intent_id?: string | null;
  /**
   * Audit record of the decision (lowercase UUID).
   */
  audit_id?: string | null;
  /**
   * Governance policy that required the approval.
   */
  policy_id?: string | null;
  policy_version?: number | null;
  /**
   * Machine reason code in snake_case, never free text.
   */
  reason_code?: string | null;
}
