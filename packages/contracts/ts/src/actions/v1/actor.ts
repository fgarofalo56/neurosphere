/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Pseudonymous reference to the principal that performed or requested an operation (Clarification 8: no email, display name or other free-text identity field). Used by ActionIntent, ApprovalDecision and AuditRecord. Derived server-side from validated identity; never taken from a request body or model output.
 */
export interface Actor {
  /**
   * Stable pseudonym of the principal, as issued by the policy store. Re-identification is a policy-store concern, not a contract field.
   */
  principal_pseudonym: string;
  /**
   * Kind of principal.
   */
  principal_kind: "user" | "service_principal" | "managed_identity" | "agent";
  /**
   * Pseudonym of the user an agent, copilot or MCP client is acting for; null when the principal acts for itself.
   */
  on_behalf_of: string | null;
}
