/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Where a decision is enforced; open-ended: readers must tolerate unknown values.
 */
export type EnforcementPoint =
  "gateway" | "tool_call" | "mcp_server" | "mcp_client" | "sdk" | "budget" | "registration";
/**
 * Canonical ID grammar cloud:customer:source:type:id. cloud is commercial or government; customer, source and type are lowercase [a-z0-9._-]; id is lowercase [a-z0-9._-] plus '/' and '='; no segment may contain ':'. Corpus: id-corpus.json. Python validator validate_canonical_id_fullmatch re-checks with re.fullmatch because Python re.search lets '$' match before a trailing newline.
 */
export type CanonicalId = string;

/**
 * Ask whether an operation is allowed (PRP-99). Carries no scope field: cloud, customer and domain come from the server-derived identity, so domain_id and customer_id are rejected as unknown keys, and no prompt or content field exists. At least one subject must be named (Python validator check_decision_request_subject in tests/contracts/validators.py). Nullable fields are optional and default to null.
 */
export interface PolicyDecisionRequest {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  decision_point: EnforcementPoint;
  operation: "model_call" | "tool_invoke" | "mcp_call" | "data_access" | "register";
  /**
   * Agent canonical id.
   */
  agent_id?: CanonicalId | null;
  /**
   * Agent version canonical id.
   */
  agent_version_id?: CanonicalId | null;
  /**
   * Tool canonical id.
   */
  tool_id?: CanonicalId | null;
  /**
   * MCP server canonical id.
   */
  mcp_server_id?: CanonicalId | null;
  /**
   * Model about to be called.
   */
  model?: {
    model_name: string | null;
    model_version: string | null;
    /**
     * Deployment canonical id.
     */
    deployment_id: CanonicalId | null;
  } | null;
  /**
   * Data assets touched.
   *
   * @maxItems 20
   */
  data_asset_ids?: CanonicalId[];
  /**
   * Kind of data access.
   */
  access?: "read" | "write" | null;
  /**
   * Deployment environment.
   */
  environment?: ("production" | "staging" | "development" | "test" | "sandbox" | "unknown") | null;
  /**
   * Caller's opaque request id for correlation.
   */
  request_ref?: string | null;
}
