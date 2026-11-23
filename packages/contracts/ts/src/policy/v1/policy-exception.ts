/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * A time-boxed exception to one rule for one subject (PRP-99; container policy_exceptions). expires_at is required and at most 365 days after requested_at (Python validator check_policy_exception_window in tests/contracts/validators.py).
 */
export interface PolicyException {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  exception_id: string;
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
   * Lowercase operator-chosen identifier.
   */
  policy_id: string;
  /**
   * Lowercase operator-chosen identifier.
   */
  rule_id: string;
  subject: TargetRef;
  /**
   * Violation it answers. Null when requested ahead of one.
   */
  violation_id?: string | null;
  status: "requested" | "approved" | "rejected" | "expired" | "revoked";
  /**
   * Machine reason code in snake_case, never free text (free text could carry names, UPNs or secrets into the audit trail).
   */
  reason_code: string;
  /**
   * Canonical pseudonymous principal id minted by the PRP-06 pseudonymizer: cloud:customer:entra:(person|principal):p-<64 hex>. Never a UPN, email address or raw directory object id.
   */
  requested_by: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  requested_at: string;
  /**
   * HITL review item that decides it.
   */
  review_item_id?: string | null;
  /**
   * Reviewer.
   */
  decided_by?: string | null;
  /**
   * When decided.
   */
  decided_at?: string | null;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  expires_at: string;
  /**
   * Audit record of the decision.
   */
  audit_id?: string | null;
}
/**
 * The entity excepted.
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
