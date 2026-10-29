/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Access grant of one Entra principal (user, application, agent or Entra group) to one target (a model API, a model deployment or an MCP server) with optional usage limits and a cost center. It is the unit a gateway enforces (PRP-34); this document is desired state only and records no enforcement. Cross-field rules enforced in this schema: target.ref carries the type segment of target.kind (model_api is a 'service' entity, model_deployment a 'model_deployment', mcp_server an 'mcp_server'); MCP grants are call-limited only (tokens_per_minute, token_quota, quota_period and requests_per_minute must be null) and model grants carry no mcp_calls_per_minute; token_quota and quota_period are set together; a user principal carries no display label (person names are never stored). The generated Pydantic model does not carry these conditionals (ADR-0004); JSON Schema is the source of truth. Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at), validate_grant_window (valid_from < valid_until when both are set).
 */
export interface Grant {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Stable canonical ID of this entity. Canonical ID (canonical_id.schema.json) whose type segment is 'grant'. The owning domain is domain_id, as for every catalog entity.
   */
  id: string;
  entity_type: "grant";
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
   * The Entra principal the grant applies to. Gateways match object_id against the token 'oid' claim (user, application, agent) or the 'groups' claim (entra_group).
   */
  principal: {
    kind: "user" | "application" | "agent" | "entra_group";
    /**
     * Entra object ID (GUID) of the principal, lowercase hyphenated form (claims are compared as exact strings). A pattern rather than format uuid keeps the generated models wire-exact strings.
     */
    object_id: string;
    /**
     * Label of an application, agent or group. Must be null for a user principal: person names are never stored in the catalog.
     */
    display?: string | null;
  };
  /**
   * What the principal may call. ref is the canonical ID of the target catalog entity; its type segment follows kind (model_api -> service, model_deployment -> model_deployment, mcp_server -> mcp_server).
   */
  target: {
    kind: "model_api" | "model_deployment" | "mcp_server";
    /**
     * Target entity. Canonical ID (canonical_id.schema.json) whose type segment is 'service' or 'model_deployment' or 'mcp_server'.
     */
    ref: string;
  };
  /**
   * Usage limits; null means no limit of that kind is declared. Token limits apply to model targets only; MCP grants are call-limited only.
   */
  limits: {
    /**
     * Token rate limit (model targets only).
     */
    tokens_per_minute?: number | null;
    /**
     * Token quota per quota_period (model targets only); set together with quota_period.
     */
    token_quota?: number | null;
    /**
     * Period of token_quota; set together with token_quota.
     */
    quota_period?: ("minute" | "hour" | "day" | "week" | "month" | "year") | null;
    /**
     * Request rate limit (model targets only).
     */
    requests_per_minute?: number | null;
    /**
     * MCP call rate limit (mcp_server targets only).
     */
    mcp_calls_per_minute?: number | null;
  };
  /**
   * Cost center usage under this grant is attributed to; null when not assigned. Restricted to characters safe in an HTTP header and a metric dimension.
   */
  cost_center?: string | null;
  /**
   * false suspends the grant without deleting it.
   */
  enabled: boolean;
  /**
   * Start of the grant; null means effective immediately.
   */
  valid_from?: string | null;
  /**
   * End of the grant (exclusive); null means open-ended.
   */
  valid_until?: string | null;
  provenance: Provenance;
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
   * Lowercase identifier token (source IDs, platforms, providers, kinds).
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
