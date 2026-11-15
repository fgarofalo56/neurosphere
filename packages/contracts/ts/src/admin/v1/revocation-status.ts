/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * OUTPUT-ONLY. Current revocation state of one principal (PRP-39; PRP-06 RevocationEntry). When revoked is false every revocation member is null. propagation_bound_seconds is the documented worst-case delay before every API replica denies (NS_REVOCATION_TTL_SECONDS); revocation is never claimed to be instant.
 */
export interface RevocationStatus {
  /**
   * Contract version of the document, major 1 with additive minor revisions (ADR-0004).
   */
  schema_version: string;
  /**
   * Canonical pseudonymous principal id minted by the PRP-06 pseudonymizer: cloud:customer:entra:(person|principal):p-<64 hex>. Never a UPN, email address or raw directory object id.
   */
  principal_id: string;
  revoked: boolean;
  mode: ("issued_before" | "until_lifted") | null;
  revoked_at: string | null;
  reason: string | null;
  revoked_by: string | null;
  propagation_bound_seconds: number;
}
