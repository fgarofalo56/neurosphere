/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * This interface was referenced by `ApprovalDecision`'s JSON-Schema
 * via the `definition` "uuid".
 */
export type Uuid = string;
/**
 * This interface was referenced by `ApprovalDecision`'s JSON-Schema
 * via the `definition` "sha256_hash".
 */
export type Sha256Hash = string;
/**
 * RFC 3339 timestamp in UTC (`Z` suffix required).
 *
 * This interface was referenced by `ApprovalDecision`'s JSON-Schema
 * via the `definition` "utc_timestamp".
 */
export type UtcTimestamp = string;

/**
 * Immutable decision on a HITL review item (PRD NS-04). Written once and never updated: a changed mind is a new review item with a new decision, never an edit, so the schema has no update-capable field. Insight review and maker-checker approval of executable changes are separate kinds. A maker-checker approval binds to the exact confirmation_hash it approves, so an approval cannot be replayed against a different target, version or diff. Rules JSON Schema cannot express are checked by `validate_maker_checker_separation` in tests/contracts/test_action_transitions.py: when self_approval_allowed is false, reviewer.principal_pseudonym differs from maker.principal_pseudonym and from maker.on_behalf_of.
 */
export interface ApprovalDecision {
  schema_version: string;
  /**
   * Server-assigned identifier of this decision (lowercase UUID).
   */
  decision_id: string;
  /**
   * Review item this decision closes or escalates (lowercase UUID).
   */
  review_item_id: string;
  /**
   * `maker_checker` approves an executable ActionIntent; `insight_review` covers relationship, evaluation, recommendation and policy-exception reviews that execute nothing.
   */
  review_kind: "maker_checker" | "insight_review";
  /**
   * ActionIntent under review; required for maker_checker, null for insight_review.
   */
  intent_id: Uuid | null;
  /**
   * confirmation_hash of the exact intent the reviewer saw; required for maker_checker. The executor refuses to proceed when it differs from the intent's current confirmation_hash.
   */
  approved_confirmation_hash: Sha256Hash | null;
  reviewer: Actor;
  /**
   * Maker: the principal who authored the change under review; required for maker_checker, null for insight_review.
   */
  maker: Actor1 | null;
  /**
   * Policy outcome at decision time: whether the maker may also be the checker. False prohibits self-approval (see `validate_maker_checker_separation`).
   */
  self_approval_allowed: boolean;
  /**
   * Outcome. `escalated` moves the review item to a higher reviewer without approving or rejecting.
   */
  decision: "approved" | "rejected" | "escalated";
  /**
   * Reviewer's justification. Required and non-empty for every decision.
   */
  reason: string;
  /**
   * Version of the approval policy evaluated for this decision.
   */
  policy_version: string;
  /**
   * Server-assigned, immutable instant of the decision.
   */
  decided_at: string;
  correlation_id: string;
}
/**
 * Checker: the principal who made this decision.
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
 * Pseudonymous reference to the principal that performed or requested an operation (Clarification 8: no email, display name or other free-text identity field). Used by ActionIntent, ApprovalDecision and AuditRecord. Derived server-side from validated identity; never taken from a request body or model output.
 */
export interface Actor1 {
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
