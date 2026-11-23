/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Why content is read or exported (PRP-99). A fragment (no schema_version) embedded by access requests and InteractionExportManifest. A code plus an optional case reference, never prose (audit content_guard forbids it).
 */
export interface InteractionAccessPurpose {
  /**
   * Purpose of the access; open-ended: readers must tolerate unknown values.
   */
  purpose_code:
    | "incident_investigation"
    | "policy_violation_review"
    | "legal_hold_review"
    | "data_subject_request"
    | "security_review"
    | "quality_review";
  /**
   * Case record id (admin record_id). Null when none.
   */
  case_ref: string | null;
}
