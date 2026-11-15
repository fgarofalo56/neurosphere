/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Request to create or replace one custom resource-scoped grant for one pseudonymous principal (PRP-39 identity API). Maps onto PRP-06 PolicyGrant: one named resource, time-bound (expires_at always required) and reason-bearing. Removing a grant is a delete of grant_id on the route, not a body. Rules JSON Schema cannot express (expires_at is in the future) are enforced by the PRP-39 handler.
 */
export interface ResourceGrantChange {
  /**
   * Contract version of the document, major 1 with additive minor revisions (ADR-0004).
   */
  schema_version: string;
  /**
   * Canonical pseudonymous principal id minted by the PRP-06 pseudonymizer: cloud:customer:entra:(person|principal):p-<64 hex>. Never a UPN, email address or raw directory object id.
   */
  principal_id: string;
  /**
   * Identifier of a record inside a policy or configuration document (assignment, grant, budget, item).
   */
  grant_id: string;
  /**
   * Canonical id cloud:customer:source:type:id (PRP-01 clarification 7). Grammar owned by catalog/v1; duplicated here as a pattern so admin v1 has no cross-area dependency.
   */
  resource_id: string;
  /**
   * @minItems 1
   * @maxItems 5
   *
   * Items: Permission a resource-scoped grant may carry (mirrors scope/v1 resource_grant).
   */
  permissions: [
    "read" | "export" | "propose_action" | "approve" | "execute",
    ...("read" | "export" | "propose_action" | "approve" | "execute")[],
  ];
  /**
   * RFC 3339 timestamp in UTC (Z suffix required).
   */
  expires_at: string;
  /**
   * Machine reason code in snake_case, never free text (free text could carry names, UPNs or secrets into the audit trail).
   */
  reason: string;
}
