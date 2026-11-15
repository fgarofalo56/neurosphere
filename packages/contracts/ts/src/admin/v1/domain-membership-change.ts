/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Request to add or remove one pseudonymous principal's membership of one domain (PRP-39 identity API). Maps onto PRP-06 PrincipalPolicy.domain_memberships. Membership alone grants no permission; roles and grants do.
 */
export interface DomainMembershipChange {
  /**
   * Contract version of the document, major 1 with additive minor revisions (ADR-0004).
   */
  schema_version: string;
  op: "add" | "remove";
  /**
   * Canonical pseudonymous principal id minted by the PRP-06 pseudonymizer: cloud:customer:entra:(person|principal):p-<64 hex>. Never a UPN, email address or raw directory object id.
   */
  principal_id: string;
  /**
   * Canonical Domain id (type segment 'domain'). No wildcard or all-domains form exists.
   */
  domain_id: string;
  /**
   * Machine reason code in snake_case, never free text (free text could carry names, UPNs or secrets into the audit trail).
   */
  reason: string;
}
