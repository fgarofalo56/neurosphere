/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Lifecycle state of a durable ActionIntent (PRP.md section 3): drafted -> validated -> awaiting_confirmation -> awaiting_approval -> executing -> succeeded/failed/rolled_back/expired. Which (from, to) moves are legal is NOT encoded here; it is the allowlist in ./transitions.json (Clarification 11). This enum is distinct from the HITL review-item enum in ./review-item-state.schema.json (Clarification 12).
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
 * Shape of ./transitions.json: the allowlist of legal ActionState (from, to) pairs (Clarification 11). Any pair not listed is forbidden, including self-transitions and every move out of a terminal state; there is no deny list. PRP-17 enforces from this data. Rules JSON Schema cannot express are checked by `validate_transition_allowlist` in tests/contracts/test_action_transitions.py: (from, to) pairs are unique, no pair has from == to, no pair starts at a terminal state, initial_state is not terminal, and every non-terminal state is reachable from initial_state and can reach a terminal state.
 */
export interface ActionTransitionAllowlist {
  schema_version: string;
  /**
   * Which state machine this allowlist governs.
   */
  state_machine: "action_intent";
  initial_state: ActionState;
  /**
   * @minItems 1
   */
  terminal_states: [ActionState, ...ActionState[]];
  /**
   * @minItems 1
   */
  transitions: [Transition, ...Transition[]];
}
/**
 * This interface was referenced by `ActionTransitionAllowlist`'s JSON-Schema
 * via the `definition` "transition".
 */
export interface Transition {
  from: ActionState;
  to: ActionState;
  /**
   * Human-readable condition under which the executor may take this transition.
   */
  guard: string;
}
