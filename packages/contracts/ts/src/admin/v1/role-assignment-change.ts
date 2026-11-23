/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Request to assign or remove one domain-scoped role for one pseudonymous principal (PRP-39 identity API). Maps onto PRP-06 PolicyRoleAssignment: assign upserts the assignment with assignment_id, remove deletes it. Privileged roles (admin, security_auditor) must carry expires_at, as PolicyRoleAssignment requires; there is no tenant-wide, wildcard or permanent privileged form. The caller's identity and permission come from the server-derived IdentityScope, never from this body. Rules JSON Schema cannot express (expires_at is in the future) are enforced by the PRP-39 handler.
 */
export interface RoleAssignmentChange {
  /**
   * Contract version of the document, major 1 with additive minor revisions (ADR-0004).
   */
  schema_version: string;
  /**
   * assign: create or replace the assignment (role and domain_ids required). remove: delete it (role and domain_ids optional, echoed for audit).
   */
  op: "assign" | "remove";
  /**
   * Canonical pseudonymous principal id minted by the PRP-06 pseudonymizer: cloud:customer:entra:(person|principal):p-<64 hex>. Never a UPN, email address or raw directory object id.
   */
  principal_id: string;
  /**
   * Identifier of a record inside a policy or configuration document (assignment, grant, budget, item).
   */
  assignment_id: string;
  /**
   * Platform role (NS-08). admin, security_auditor and interaction_investigator are privileged and always time-bound. Open-ended: readers must tolerate unknown values.
   */
  role?:
    | "viewer"
    | "analyst"
    | "domain_steward"
    | "admin"
    | "security_auditor"
    | "interaction_investigator";
  /**
   * Domains the role applies to. At least one; there is no tenant-wide form.
   *
   * @minItems 1
   * @maxItems 1024
   *
   * Items: Canonical Domain id (type segment 'domain'). No wildcard or all-domains form exists.
   */
  domain_ids?: [string, ...string[]];
  /**
   * When the assignment lapses. Required for admin and security_auditor.
   */
  expires_at?: string;
  /**
   * Machine reason code in snake_case, never free text (free text could carry names, UPNs or secrets into the audit trail).
   */
  reason: string;
}
