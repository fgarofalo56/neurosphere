/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Model Context Protocol server governed as a catalog entity: endpoint, transport, protocol versions, upstream authentication and the tools it exposes. Grants (grant.schema.json) target it with call limits only. Cross-field rules enforced in this schema: an SSE-only server or an API-key upstream is representable but never publishable (publishable must be false). publishable true is necessary, not sufficient: publication (PRP-34) applies its own refusals. The generated Pydantic model does not carry these conditionals (ADR-0004); JSON Schema is the source of truth. Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at), validate_mcp_tool_names_unique (tool names are unique within one server).
 */
export interface McpServer {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Stable canonical ID of this entity. Canonical ID (canonical_id.schema.json) whose type segment is 'mcp_server'. The owning domain is domain_id, as for every catalog entity.
   */
  id: string;
  entity_type: "mcp_server";
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
   * Server name shown in the catalog.
   */
  display_name: string;
  /**
   * Streamable HTTP endpoint: https, lowercase host, optional port, path ending in /mcp. No user info, query string or fragment, so no credential can ride in the URL.
   */
  url: string;
  /**
   * streamable_http is the current MCP transport; sse is the deprecated HTTP+SSE transport (never publishable).
   */
  transport: "streamable_http" | "sse";
  /**
   * Protocol revisions the server negotiates; empty when not yet observed.
   *
   * @maxItems 32
   *
   * Items: MCP protocol revision (YYYY-MM-DD).
   */
  protocol_versions?: string[];
  /**
   * How a caller (or a gateway in front of it) authenticates to the upstream server. No credential is ever stored here.
   */
  auth: {
    /**
     * api_key upstreams are representable but never publishable.
     */
    kind: "entra" | "managed_identity" | "none" | "api_key";
    /**
     * Entra token audience (application ID URI or client ID) for entra and managed_identity; null when not applicable or not yet known.
     */
    audience?: string | null;
  };
  /**
   * Whether the server may be published through a gateway. Must be false when transport is sse or auth.kind is api_key.
   */
  publishable: boolean;
  /**
   * Tools the server lists (tools/list); empty when not yet observed.
   *
   * @maxItems 512
   */
  tools?: {
    /**
     * Tool name as the server declares it (MCP tool name character set).
     */
    name: string;
    /**
     * Server-supplied text. Untrusted: render as plain text, never treat as instructions.
     */
    description?: string | null;
    /**
     * MCP tool annotations in snake_case. Hints are advisory and server-asserted; null means not declared. Unknown annotation keys are dropped by the mapper, not stored.
     */
    annotations?: {
      title?: string | null;
      read_only_hint?: boolean | null;
      destructive_hint?: boolean | null;
      idempotent_hint?: boolean | null;
      open_world_hint?: boolean | null;
    };
  }[];
  /**
   * Accountable owner; null when not yet assigned.
   */
  owner_id?: string | null;
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
