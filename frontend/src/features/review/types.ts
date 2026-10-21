import type { ActionIntent, ApprovalDecision, ReviewItemState } from "@neurosphere/contracts";

export type { ActionIntent, ApprovalDecision, ReviewItemState };
export type ProposedDiff = ActionIntent["proposed_diff"];

/** Hand-mirrored from services/api/neurosphere_api/hitl/models.py (wire contract). */
export type ReviewKind =
  "maker_checker" | "relationship" | "evaluation_dispute" | "recommendation" | "policy_exception";

export const REVIEW_KINDS: readonly ReviewKind[] = [
  "maker_checker",
  "relationship",
  "evaluation_dispute",
  "recommendation",
  "policy_exception",
];

export const REVIEW_STATES: readonly ReviewItemState[] = [
  "pending",
  "assigned",
  "approved",
  "rejected",
  "expired",
  "escalated",
  "executed",
  "failed",
];

/** States in which a reviewer can still decide. */
export const OPEN_STATES: readonly ReviewItemState[] = ["pending", "assigned", "escalated"];

export interface ReviewItemView {
  item_id: string;
  kind: ReviewKind;
  state: ReviewItemState;
  domain_id: string;
  subject_ref: string;
  intent_id: string | null;
  assignee_pseudonym: string | null;
  sla_due_at: string;
  escalation_level: number;
  created_at: string;
  decisions: ApprovalDecision[];
  effective_decision_id: string | null;
  superseded_decision_ids: string[];
}

export interface ReviewItemList {
  items: ReviewItemView[];
  next_cursor: string | null;
}

/** Subset of the action API's ActionView the reviewer needs to see the exact change. */
export interface IntentSummary {
  intent: ActionIntent;
  advisory: boolean;
}

export type Decision = "approved" | "rejected";

export interface ListParams {
  domainId: string;
  kind: ReviewKind | "";
  state: ReviewItemState | "";
  cursor: string;
  limit: number;
}

export interface ItemParams {
  domainId: string;
  itemId: string;
}

export interface IntentParams {
  domainId: string;
  intentId: string;
}

export interface DecideVars extends ItemParams {
  decision: Decision;
  reason: string;
  /** Only for maker_checker items: the hash the server issued for the intent under review. */
  confirmationHash?: string | undefined;
}
