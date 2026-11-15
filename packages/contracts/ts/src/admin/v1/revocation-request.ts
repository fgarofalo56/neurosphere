/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Request to revoke one principal's sessions (PRP-39; PRP-06 revocation service). The target principal is named by the route, never by this body. issued_before: deny every token issued at or before the revocation (plus clock skew); the principal may sign in again. until_lifted: deny every token until an operator lifts the revocation. Revocation is bounded by NS_REVOCATION_TTL_SECONDS, not instant.
 */
export interface RevocationRequest {
  /**
   * Contract version of the document, major 1 with additive minor revisions (ADR-0004).
   */
  schema_version: string;
  /**
   * Machine reason code in snake_case, never free text (free text could carry names, UPNs or secrets into the audit trail).
   */
  reason: string;
  mode: "issued_before" | "until_lifted";
}
