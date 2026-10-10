/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * RFC 3339 timestamp in UTC (`Z` suffix required).
 *
 * This interface was referenced by `ActionIntent`'s JSON-Schema
 * via the `definition` "utc_timestamp".
 */
export type UtcTimestamp = string;
/**
 * Lowercase hex SHA-256 digest with algorithm prefix.
 *
 * This interface was referenced by `ActionIntent`'s JSON-Schema
 * via the `definition` "sha256_hash".
 */
export type Sha256Hash = string;
/**
 * Current lifecycle state.
 */
export type ActionState =
  | "drafted"
  | "validated"
  | "awaiting_confirmation"
  | "awaiting_approval"
  | "executing"
  | "succeeded"
  | "failed"
  | "rolled_back"
  | "expired";
/**
 * This interface was referenced by `ActionIntent`'s JSON-Schema
 * via the `definition` "uuid".
 */
export type Uuid = string;
/**
 * This interface was referenced by `ActionIntent`'s JSON-Schema
 * via the `definition` "correlation_id".
 */
export type CorrelationId = string;

/**
 * Durable intent executed by the single action executor shared by button, chat, REST and MCP (PRP.md section 3, PRD NS-06). The intent binds actor, target, target_version, proposed_diff and confirmation expiry into confirmation_hash, defined field-by-field in ./confirmation-hash.json, so every channel computes the same value. Legal state changes are the allowlist in ./transitions.json; enforcement belongs to PRP-17. Rules JSON Schema cannot express are checked by Python validators in tests/contracts/test_action_transitions.py: `validate_confirmation_hash` (confirmation_hash equals the recomputed hash), `validate_state_transition` (every state change is an allowlisted (from, to) pair) and `validate_intent_timestamps` (created_at <= state_changed_at, and confirmation_expires_at > created_at).
 */
export interface ActionIntent {
  /**
   * Contract version of this document; major must match the v1 directory.
   */
  schema_version: string;
  /**
   * Server-assigned identifier of this intent (lowercase UUID).
   */
  intent_id: string;
  /**
   * Kind of governed action, lowercase snake_case (for example `model_swap`, `budget_cap_change`). Kinds the target has no supported write connector for are advisory and never reach `executing`.
   */
  action_kind: string;
  actor: Actor;
  target: TargetRef;
  /**
   * Exact version or ETag of the target the diff was computed against. Rechecked at execution; a mismatch fails with error code `stale_version`. Hashed into confirmation_hash.
   */
  target_version: string;
  proposed_diff: ProposedDiff;
  /**
   * Results of prerequisite checks evaluated during validation (permission, policy, connector support, target health, budget).
   */
  prerequisite_results: PrerequisiteResult[];
  /**
   * Evidence the action is based on (recommendation, evaluation, telemetry or cost references). Not hashed.
   */
  evidence: EvidenceRef[];
  /**
   * SHA-256 over exactly these fields: target, target_version, proposed_diff, confirmation_expires_at, actor; canonicalized with RFC 8785 (JCS) as specified in ./confirmation-hash.json. Excludes channel, idempotency_key, state and evidence so button, chat, REST and MCP produce the same value. Null until the intent reaches awaiting_confirmation. Python validator: `validate_confirmation_hash`.
   */
  confirmation_hash: Sha256Hash | null;
  /**
   * Expiry of the confirmation; hashed. After this instant the intent may only move to `expired`. Null until the intent reaches awaiting_confirmation.
   */
  confirmation_expires_at: UtcTimestamp | null;
  /**
   * Required on every intent. Replays with the same key return the original intent and result instead of executing twice.
   */
  idempotency_key: string;
  /**
   * Channel the intent arrived through. Not hashed: the same intent from any channel has the same confirmation_hash.
   */
  channel: "button" | "chat" | "rest" | "mcp";
  state: ActionState;
  /**
   * Machine-readable reason for the current state, lowercase snake_case (for example `approval_rejected`, `stale_version`, `confirmation_expired`). Required non-null for failed, rolled_back and expired; null otherwise allowed.
   */
  status_reason: string | null;
  /**
   * True when the executor must plan and verify prerequisites without applying the change.
   */
  dry_run: boolean;
  /**
   * Correlation ID propagated to audit records and error responses.
   */
  correlation_id: string;
  /**
   * RFC 3339 timestamp in UTC (`Z` suffix required).
   */
  created_at: string;
  /**
   * RFC 3339 timestamp in UTC (`Z` suffix required).
   */
  state_changed_at: string;
}
/**
 * Principal that requested the action. Hashed into confirmation_hash.
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
 * Resource the action changes. Hashed into confirmation_hash.
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
 * Exact change shown to the user for confirmation. Hashed into confirmation_hash.
 */
export interface ProposedDiff {
  /**
   * Diff encoding. Only RFC 6902 JSON Patch in v1.
   */
  format: "json_patch";
  /**
   * @minItems 1
   * @maxItems 256
   */
  operations: [PatchOperation, ...PatchOperation[]];
}
/**
 * One RFC 6902 operation. add/replace/test require `value`; move/copy require `from`; remove takes neither.
 *
 * This interface was referenced by `ActionIntent`'s JSON-Schema
 * via the `definition` "patch_operation".
 */
export interface PatchOperation {
  op: "add" | "remove" | "replace" | "move" | "copy" | "test";
  /**
   * RFC 6901 JSON Pointer.
   */
  path: string;
  /**
   * RFC 6901 JSON Pointer source for move/copy.
   */
  from?: string;
  /**
   * New value (any JSON) for add/replace/test.
   */
  value?: unknown;
}
/**
 * This interface was referenced by `ActionIntent`'s JSON-Schema
 * via the `definition` "prerequisite_result".
 */
export interface PrerequisiteResult {
  /**
   * Prerequisite check name, lowercase snake_case (for example `actor_permission`, `write_connector_supported`).
   */
  check_id: string;
  /**
   * `unknown` when the check could not be evaluated; never coerced to passed.
   */
  status: "passed" | "failed" | "warning" | "not_applicable" | "unknown";
  /**
   * Short human-readable explanation; null when none.
   */
  detail: string | null;
  evaluated_at: UtcTimestamp;
  evidence_ids: string[];
}
/**
 * This interface was referenced by `ActionIntent`'s JSON-Schema
 * via the `definition` "evidence_ref".
 */
export interface EvidenceRef {
  evidence_id: string;
  kind:
    | "recommendation"
    | "evaluation_result"
    | "telemetry_query"
    | "cost_record"
    | "catalog_entity"
    | "policy"
    | "document";
  /**
   * Pointer to the evidence (canonical ID or stored-document ID). Never an inline body.
   */
  ref: string;
  /**
   * When the evidence was observed; null when unknown.
   */
  observed_at: UtcTimestamp | null;
}
/**
 * RFC 6902 JSON Patch against the target document at target_version. `value` members are opaque target data validated by the write connector and must never hold secret material (use vault references).
 *
 * This interface was referenced by `ActionIntent`'s JSON-Schema
 * via the `definition` "proposed_diff".
 */
export interface ProposedDiff1 {
  /**
   * Diff encoding. Only RFC 6902 JSON Patch in v1.
   */
  format: "json_patch";
  /**
   * @minItems 1
   * @maxItems 256
   */
  operations: [PatchOperation, ...PatchOperation[]];
}
