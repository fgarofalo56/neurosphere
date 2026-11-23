/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * How a policy or enforcement point acts: off (not evaluated), audit (evaluated and recorded, never blocks; the default, GD-7) or enforce (blocks). Enforce is set only by an approved action.
 */
export type EnforcementMode = "off" | "audit" | "enforce";
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
 * The answer to a PolicyDecisionRequest (PRP-99). cache_ttl_seconds is 0 to 3600: how long the caller may reuse it. degraded is true when the engine answered from a stale or partial policy set.
 */
export interface PolicyDecisionResponse {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  decision_id: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  decided_at: string;
  effect: "allow" | "deny" | "audit";
  mode: EnforcementMode;
  /**
   * @maxItems 20
   */
  matches: PolicyDecisionMatch[];
  /**
   * @maxItems 8
   *
   * Items: Machine reason code in snake_case, never free text (free text could carry names, UPNs or secrets into the audit trail).
   */
  reason_codes: string[];
  cache_ttl_seconds: number;
  /**
   * Digest of the policy set evaluated.
   */
  policy_set_digest: string;
  degraded: boolean;
}
/**
 * One rule that matched the request.
 *
 * This interface was referenced by `PolicyDecisionResponse`'s JSON-Schema
 * via the `definition` "match".
 */
export interface PolicyDecisionMatch {
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
  effect: "allow" | "deny" | "audit";
}
