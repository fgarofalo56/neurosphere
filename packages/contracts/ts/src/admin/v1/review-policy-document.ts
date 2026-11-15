/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * This interface was referenced by `ReviewPolicyDocument`'s JSON-Schema
 * via the `definition` "review_kind".
 */
export type ReviewKind =
  "maker_checker" | "relationship" | "evaluation_dispute" | "recommendation" | "policy_exception";
/**
 * Positive duration in whole seconds, at most 90 days.
 *
 * This interface was referenced by `ReviewPolicyDocument`'s JSON-Schema
 * via the `definition` "duration_seconds".
 */
export type DurationSeconds = number;

/**
 * Operator review policy (PRP-44), mapping onto core HITL ReviewPolicyRegistry: kind_defaults become the per-review-kind defaults and action_overrides the (review_kind, action_kind) overrides. Durations are integer seconds (core ReviewPolicy timedeltas). A kind missing from kind_defaults has no policy and fails closed (capability_unavailable), so maker_checker is required. Self-approval stays forbidden unless an override says otherwise. Rules JSON Schema cannot express are checked by tests/contracts/validators.py::check_review_policy_document: review kinds in kind_defaults and (review_kind, action_kind) pairs in action_overrides are unique.
 */
export interface ReviewPolicyDocument {
  /**
   * Contract version of the document, major 1 with additive minor revisions (ADR-0004).
   */
  schema_version: string;
  /**
   * Version label copied onto every ReviewPolicy built from this document.
   */
  policy_version: string;
  /**
   * @minItems 1
   * @maxItems 16
   */
  kind_defaults: [ReviewKindDefault, ...ReviewKindDefault[]];
  /**
   * @maxItems 64
   */
  action_overrides: ReviewActionOverride[];
}
/**
 * This interface was referenced by `ReviewPolicyDocument`'s JSON-Schema
 * via the `definition` "kind_default".
 */
export interface ReviewKindDefault {
  review_kind: ReviewKind;
  policy: ReviewPolicySettings;
}
/**
 * One core ReviewPolicy. Every duration is positive.
 *
 * This interface was referenced by `ReviewPolicyDocument`'s JSON-Schema
 * via the `definition` "policy".
 */
export interface ReviewPolicySettings {
  self_approval_forbidden: boolean;
  /**
   * Permission the reviewer needs on the item's domain.
   */
  approver_permission: "action.approve" | "catalog.curate";
  assignment_timeout_seconds: DurationSeconds;
  sla_seconds: DurationSeconds;
  escalation_step_seconds: DurationSeconds;
  max_escalations: number;
  expiry_seconds: DurationSeconds;
}
/**
 * This interface was referenced by `ReviewPolicyDocument`'s JSON-Schema
 * via the `definition` "action_override".
 */
export interface ReviewActionOverride {
  review_kind: ReviewKind;
  /**
   * Action kind (actions/v1 ActionIntent action_kind).
   */
  action_kind: string;
  policy: ReviewPolicySettings;
}
