/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Closed typed rule kind that selects the parameter object; open-ended: readers must tolerate unknown values (PRP-110 adds identity_entitlement).
 */
export type PolicyRuleKind =
  | "model_allow_list"
  | "data_sensitivity_access"
  | "residency"
  | "budget"
  | "required_owner"
  | "required_attestation"
  | "required_approval"
  | "content_rule"
  | "registration_required";
/**
 * How serious a violation of the policy or rule is.
 */
export type PolicySeverity = "low" | "medium" | "high" | "critical";

/**
 * One deduplicated finding that an entity breaks a rule (PRP-99; container policy_violations). Evidence is references only: no content, no query text.
 */
export interface PolicyViolation {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  violation_id: string;
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
  policy_version: number;
  /**
   * Lowercase operator-chosen identifier.
   */
  rule_id: string;
  rule_kind: PolicyRuleKind;
  severity: PolicySeverity;
  subject: TargetRef;
  status: "open" | "excepted" | "resolved" | "superseded";
  /**
   * Digest of policy, rule and subject so one breach is one violation.
   */
  dedup_key: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  first_seen_at: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  last_seen_at: string;
  occurrence_count: number;
  /**
   * @minItems 1
   * @maxItems 50
   */
  evidence: [PolicyViolationEvidence, ...PolicyViolationEvidence[]];
  /**
   * Exception that covers it. Null when none.
   */
  exception_id?: string | null;
  /**
   * How it was resolved. Null while open.
   */
  resolution?: {
    /**
     * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
     */
    resolved_at: string;
    /**
     * Machine reason code in snake_case, never free text (free text could carry names, UPNs or secrets into the audit trail).
     */
    reason_code: string;
    /**
     * Action intent, when the fix went through one.
     */
    intent_id: string | null;
    /**
     * Audit record of the resolution.
     */
    audit_id: string | null;
  } | null;
  correlation_id: string;
  evaluator_version: string;
}
/**
 * The entity in violation.
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
 * A reference to what showed the breach.
 *
 * This interface was referenced by `PolicyViolation`'s JSON-Schema
 * via the `definition` "evidence".
 */
export interface PolicyViolationEvidence {
  /**
   * What `ref` points at. Open-ended: readers must tolerate unknown values.
   */
  evidence_kind:
    | "catalog_entity"
    | "relation"
    | "interaction_record"
    | "aggregate_window"
    | "audit_record"
    | "telemetry_event"
    | "budget_status";
  /**
   * Opaque reference id or canonical id.
   */
  ref: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  observed_at: string;
}
