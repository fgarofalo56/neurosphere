/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * This interface was referenced by `EvidenceObservation`'s JSON-Schema
 * via the `definition` "utc_timestamp".
 */
export type UtcTimestamp = string;

/**
 * What one read-only evidence source saw for a domain in a window (PRP-56). Counts, timestamps and ids only: no entity bodies, no prompts, no principal names. status: observed (the source answered), partial (answered with a cap or a gap), unavailable (store missing or down; reason_code says why), not_collected (the source cannot count this). Unknown numbers are null, never 0.
 */
export interface EvidenceObservation {
  schema_version: string;
  source_id:
    | "catalog_ownership"
    | "audit_chain"
    | "hitl_decisions"
    | "evaluation_results"
    | "cost_attribution";
  status: "observed" | "partial" | "unavailable" | "not_collected";
  /**
   * snake_case machine reason; null when status is observed.
   */
  reason_code: string | null;
  window_start: UtcTimestamp;
  window_end: UtcTimestamp;
  /**
   * Newest timestamp the source saw; null when none or unknown.
   */
  latest_at: UtcTimestamp | null;
  truncated: boolean;
  /**
   * @maxItems 20
   */
  measures: {
    name: string;
    value: number | null;
  }[];
}
