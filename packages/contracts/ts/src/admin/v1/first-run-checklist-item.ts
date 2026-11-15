/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * OUTPUT-ONLY. One row of the operator first-run checklist (PRP-45): whether a platform component is configured, with a machine reason and a documentation path when it is not complete. complete carries no reason; every other status carries one, so the console can say why a component is missing, disabled or failing instead of showing a blank.
 */
export interface FirstRunChecklistItem {
  /**
   * Contract version of the document, major 1 with additive minor revisions (ADR-0004).
   */
  schema_version: string;
  /**
   * Lowercase operator-chosen identifier.
   */
  item_id: string;
  /**
   * Lowercase operator-chosen identifier.
   */
  component: string;
  status: "complete" | "missing" | "disabled" | "not_applicable" | "error";
  reason: string | null;
  doc_path: string | null;
  /**
   * true when the platform cannot serve its core function without this component.
   */
  required: boolean;
}
