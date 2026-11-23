/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Reason as stored by PRP-06 (PolicyRoleAssignment.reason, PolicyGrant.reason: 1 to 512 characters). Writes made through admin v1 store reason codes.
 *
 * This interface was referenced by `PrincipalAccessSummary`'s JSON-Schema
 * via the `definition` "stored_reason".
 */
export type StoredReason = string;

/**
 * OUTPUT-ONLY. Everything one pseudonymous principal can do, as stored in the PRP-06 policy store, for the PRP-39 identity console: domain memberships, role assignments with expiry, resource-scoped grants and the current revocation state. It is a view of stored policy, not a derived IdentityScope, and is never accepted as input. No name, email, UPN or raw directory object id appears; re-identification is a policy-store concern.
 */
export interface PrincipalAccessSummary {
  /**
   * Contract version of the document, major 1 with additive minor revisions (ADR-0004).
   */
  schema_version: string;
  principal: AccessSummaryPrincipal;
  /**
   * Customer segment of the canonical id grammar (the tenant deployment).
   */
  customer_id: string;
  /**
   * Azure cloud boundary. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Policy store version the summary was read at.
   */
  policy_version: string;
  /**
   * @maxItems 1024
   *
   * Items: Canonical id cloud:customer:source:type:id (PRP-01 clarification 7). Grammar owned by catalog/v1; duplicated here as a pattern so admin v1 has no cross-area dependency.
   */
  memberships: string[];
  /**
   * @maxItems 64
   */
  assignments: AccessSummaryAssignment[];
  /**
   * @maxItems 4096
   */
  grants: AccessSummaryGrant[];
  revocation: RevocationStatus;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required).
   */
  generated_at: string;
}
/**
 * This interface was referenced by `PrincipalAccessSummary`'s JSON-Schema
 * via the `definition` "principal".
 */
export interface AccessSummaryPrincipal {
  /**
   * Canonical pseudonymous principal id minted by the PRP-06 pseudonymizer: cloud:customer:entra:(person|principal):p-<64 hex>. Never a UPN, email address or raw directory object id.
   */
  principal_id: string;
  principal_kind: "user" | "service_principal";
}
/**
 * A stored role assignment. expires_at is null only for non-privileged roles.
 *
 * This interface was referenced by `PrincipalAccessSummary`'s JSON-Schema
 * via the `definition` "assignment".
 */
export interface AccessSummaryAssignment {
  /**
   * Identifier of a record inside a policy or configuration document (assignment, grant, budget, item).
   */
  assignment_id: string;
  /**
   * Platform role (NS-08). admin, security_auditor and interaction_investigator are privileged and always time-bound. Open-ended: readers must tolerate unknown values.
   */
  role:
    | "viewer"
    | "analyst"
    | "domain_steward"
    | "admin"
    | "security_auditor"
    | "interaction_investigator";
  /**
   * @minItems 1
   * @maxItems 1024
   *
   * Items: Canonical id cloud:customer:source:type:id (PRP-01 clarification 7). Grammar owned by catalog/v1; duplicated here as a pattern so admin v1 has no cross-area dependency.
   */
  domain_ids: [string, ...string[]];
  expires_at: string | null;
  reason: StoredReason | null;
}
/**
 * This interface was referenced by `PrincipalAccessSummary`'s JSON-Schema
 * via the `definition` "grant".
 */
export interface AccessSummaryGrant {
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
  reason: StoredReason;
}
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
