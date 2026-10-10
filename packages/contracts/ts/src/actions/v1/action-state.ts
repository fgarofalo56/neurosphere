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
