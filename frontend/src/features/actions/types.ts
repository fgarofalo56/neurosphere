import type { ActionIntent, ActionState } from "@neurosphere/contracts";

export type { ActionIntent, ActionState };
export type ProposedDiff = ActionIntent["proposed_diff"];
export type PatchOperation = ProposedDiff["operations"][number];
export type Channel = ActionIntent["channel"];

/** Hand-mirrored from services/api/neurosphere_api/actions/models.py (wire contract). */
export type ExecutionPhase =
  | "pending"
  | "rechecked"
  | "dry_run_done"
  | "applying"
  | "applied"
  | "canary"
  | "verifying"
  | "rolling_back"
  | "done";

export type CanaryOutcome = "passed" | "failed" | "verify_only";

export interface ExecutionView {
  phase: ExecutionPhase;
  canary: CanaryOutcome | null;
  verify_matched: boolean | null;
  rolled_back: boolean;
}

export interface ActionView {
  intent: ActionIntent;
  advisory: boolean;
  requires_approval: boolean;
  self_approval_forbidden: boolean;
  review_item_id: string | null;
  execution: ExecutionView | null;
}

export interface ActionListResponse {
  items: ActionView[];
  next_cursor: string | null;
}

export interface EmergencyDisableView {
  disabled: boolean;
  reason: string | null;
  changed_by: string | null;
  changed_at: string | null;
}

/** Body of POST .../intents. No identity, customer or domain fields: the server derives them. */
export interface DraftIntentRequest {
  action_kind: string;
  target: { canonical_id: string; entity_type: string };
  target_version: string;
  proposed_diff: ProposedDiff;
  evidence: ActionIntent["evidence"];
  idempotency_key: string;
  channel: Channel;
  dry_run: boolean;
}

export const ACTION_STATES: readonly ActionState[] = [
  "drafted",
  "validated",
  "awaiting_confirmation",
  "awaiting_approval",
  "executing",
  "succeeded",
  "failed",
  "rolled_back",
  "expired",
];

export interface ListParams {
  domainId: string;
  state: ActionState | "";
  cursor: string;
  limit: number;
}

export interface DetailParams {
  domainId: string;
  intentId: string;
}

export interface IntentVars {
  domainId: string;
  intentId: string;
}

export interface DraftVars {
  domainId: string;
  request: DraftIntentRequest;
}

export interface ConfirmVars extends IntentVars {
  confirmationHash: string;
}
