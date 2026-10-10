/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * This interface was referenced by `AuditRecord`'s JSON-Schema
 * via the `definition` "sha256_hash".
 */
export type Sha256Hash = string;
/**
 * This interface was referenced by `AuditRecord`'s JSON-Schema
 * via the `definition` "uuid".
 */
export type Uuid = string;
/**
 * RFC 3339 timestamp in UTC (`Z` suffix required).
 *
 * This interface was referenced by `AuditRecord`'s JSON-Schema
 * via the `definition` "utc_timestamp".
 */
export type UtcTimestamp = string;

/**
 * Append-only, hash-chained audit evidence (PRP.md section 3, PRD NS-06 'audit before/after'). Kinds: `before` (target state captured before a change), `after` (outcome and target state after), `denied` (a query, tool, export, push or action that authorization or policy refused). There is no update-capable field: no updated_at, modified_by, etag, version, status or deleted flag; corrections are new records. previous_hash is required for every record except the chain head (sequence 0), where it is null. Rules JSON Schema cannot express are checked by `validate_audit_chain` in tests/contracts/test_schemas.py: record_hash equals sha256 over the RFC 8785 (JCS) canonical form of the record without record_hash; within a chain_id, sequence is contiguous from 0 and each previous_hash equals the preceding record's record_hash.
 */
export interface AuditRecord {
  schema_version: string;
  /**
   * Server-assigned identifier of this record (lowercase UUID).
   */
  audit_id: string;
  /**
   * Identifier of the hash chain this record belongs to (for example one chain per domain cell).
   */
  chain_id: string;
  /**
   * Zero-based position in the chain. 0 is the chain head.
   */
  sequence: number;
  /**
   * record_hash of the preceding record in the chain. Null only for the chain head (sequence 0); required otherwise.
   */
  previous_hash: Sha256Hash | null;
  /**
   * sha256 over the JCS-canonical record excluding this field.
   */
  record_hash: string;
  kind: "before" | "after" | "denied";
  /**
   * Server-assigned, immutable instant the record was appended.
   */
  recorded_at: string;
  actor: Actor;
  /**
   * scope_hash of the server-derived IdentityScope the request was evaluated under.
   */
  scope_hash: string;
  correlation_id: string;
  /**
   * Dotted lowercase operation name (for example `action.execute`, `graph.query`, `report.export`, `mcp.tool_call`).
   */
  operation: string;
  /**
   * Channel the request arrived through; null for internal workers.
   */
  channel: "button" | "chat" | "rest" | "mcp" | "websocket" | "worker" | null;
  /**
   * ActionIntent this record belongs to; null for non-action operations.
   */
  intent_id: Uuid | null;
  /**
   * Target and captured state. Required for before and after; null allowed for denied when no target was resolved.
   */
  subject: Subject | null;
  /**
   * Result of the change. Required for after; null for before and denied.
   */
  outcome: Outcome | null;
  /**
   * Why the request was refused. Required for denied; null otherwise.
   */
  denial: Denial | null;
}
/**
 * Principal whose request produced this record.
 */
export interface Actor {
  /**
   * Stable pseudonym of the principal, as issued by the policy store. Re-identification is a policy-store concern, not a contract field.
   */
  principal_pseudonym: string;
  /**
   * Kind of principal.
   */
  principal_kind: "user" | "service_principal" | "managed_identity" | "agent";
  /**
   * Pseudonym of the user an agent, copilot or MCP client is acting for; null when the principal acts for itself.
   */
  on_behalf_of: string | null;
}
/**
 * This interface was referenced by `AuditRecord`'s JSON-Schema
 * via the `definition` "subject".
 */
export interface Subject {
  target: TargetRef;
  /**
   * Version or ETag observed; null when unknown.
   */
  target_version: string | null;
  /**
   * sha256 of the captured target state; null when the state could not be read.
   */
  state_digest: Sha256Hash | null;
  /**
   * Pointer to the stored, redacted snapshot used for rollback evidence; never an inline body. Null when none was stored.
   */
  snapshot_ref: string | null;
}
/**
 * Reference to the resource an action changes or an audit record concerns. `canonical_id` uses the catalog grammar `cloud:customer:source:type:id` (Clarification 7); the pattern here mirrors it and the catalog/v1 grammar is authoritative. Python validator `validate_target_ref_matches_catalog_grammar` in tests/contracts/test_canonical_ids.py checks this pattern against the catalog ID corpus so the two cannot drift. The version being acted on is carried beside this object (ActionIntent.target_version), not inside it, so it is hashed as its own field.
 */
export interface TargetRef {
  /**
   * Cloud/customer/source qualified canonical ID of the target.
   */
  canonical_id: string;
  /**
   * Catalog entity type of the target, lowercase snake_case (for example `model_deployment`, `agent_version`).
   */
  entity_type: string;
}
/**
 * This interface was referenced by `AuditRecord`'s JSON-Schema
 * via the `definition` "outcome".
 */
export interface Outcome {
  /**
   * Final ActionState the intent reached; mirrors the terminal states of ../../actions/v1/action-state.schema.json.
   */
  result: "succeeded" | "failed" | "rolled_back";
  /**
   * True only when the actual change on the target was read back and matched (no catalog-only pretend changes).
   */
  verified: boolean;
  detail: string | null;
}
/**
 * This interface was referenced by `AuditRecord`'s JSON-Schema
 * via the `definition` "denial".
 */
export interface Denial {
  /**
   * Error taxonomy code. Mirrors errors/v1 (authoritative); `validate_denial_codes_match_error_taxonomy` in tests/contracts/test_error_taxonomy.py keeps the two lists equal.
   */
  code:
    | "unauthorized"
    | "forbidden"
    | "capability_unavailable"
    | "stale_version"
    | "rate_limited"
    | "invalid_schema"
    | "dependency_transient";
  /**
   * Machine-readable reason, lowercase snake_case (for example `domain_out_of_scope`, `self_approval_prohibited`).
   */
  reason: string;
}
