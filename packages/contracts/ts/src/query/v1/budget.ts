/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Shared bounded-execution budget for every query, traversal, search, export and viewport expansion (PRP-01 clarification 15; NS-05, NS-06). timeout_ms, limit and max_depth are mandatory. The maxima here are contract ceilings; the server may clamp to lower policy values and reports the effective values and any truncation in Page. Not a standalone document, so it carries no schema_version.
 */
export interface Budget {
  /**
   * Wall-clock budget in integer milliseconds.
   */
  timeout_ms: number;
  /**
   * Maximum rows (or root items) per page.
   */
  limit: number;
  /**
   * Maximum traversal depth. 0 for non-graph queries.
   */
  max_depth: number;
  /**
   * Maximum graph nodes returned (viewport budget). Absent means the server policy default, never unbounded.
   */
  max_nodes?: number;
  /**
   * Maximum graph edges returned (viewport budget). Absent means the server policy default, never unbounded.
   */
  max_edges?: number;
}
