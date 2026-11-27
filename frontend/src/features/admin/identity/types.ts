/** The PRP-39 shapes the identity pages read (neurosphere_contracts.admin.v1). */
/**
 * admin, security_auditor and interaction_investigator are privileged: the API refuses an
 * assignment without expires_at, and an interaction_investigator assignment longer than 7 days
 * (role_assignment_too_long, PRP-104 GD-16).
 */
export type RoleName =
  | "viewer"
  | "analyst"
  | "domain_steward"
  | "admin"
  | "security_auditor"
  | "interaction_investigator";
export const ROLE_NAMES: readonly RoleName[] = [
  "viewer",
  "analyst",
  "domain_steward",
  "admin",
  "security_auditor",
  "interaction_investigator",
];

export type GrantPermission = "read" | "export" | "propose_action" | "approve" | "execute";
export const GRANT_PERMISSIONS: readonly GrantPermission[] = [
  "read",
  "export",
  "propose_action",
  "approve",
  "execute",
];

export interface AssignmentView {
  readonly assignment_id: string;
  readonly role: string;
  readonly domain_ids: readonly string[];
  readonly expires_at: string | null;
  readonly reason: string | null;
}

export interface GrantView {
  readonly grant_id: string;
  readonly resource_id: string;
  readonly permissions: readonly string[];
  readonly expires_at: string;
  readonly reason: string;
}

export interface RevocationView {
  readonly principal_id: string;
  readonly revoked: boolean;
  readonly mode: "issued_before" | "until_lifted" | null;
  readonly revoked_at: string | null;
  readonly reason: string | null;
  readonly revoked_by: string | null;
  readonly propagation_bound_seconds: number;
}

export interface PrincipalSummary {
  readonly principal: { readonly principal_id: string; readonly principal_kind: string };
  readonly policy_version: string;
  readonly memberships: readonly string[];
  readonly assignments: readonly AssignmentView[];
  readonly grants: readonly GrantView[];
  readonly revocation: RevocationView;
}

export interface PrincipalPageView {
  readonly items: readonly PrincipalSummary[];
  readonly next_cursor: string | null;
  readonly truncated: boolean;
}

export interface PrincipalListParams {
  readonly cursor: string;
  readonly limit: number;
}

/** PRP-138: where a role in the caller's own access came from. */
export type AccessSource = "entra_app_role" | "entra_group" | "policy_store";

export interface AccessRoleView {
  readonly role: string;
  readonly source: AccessSource;
  readonly mapping_entry_id: string | null;
  readonly domain_count: number;
  readonly customer_control: boolean;
  readonly expires_at: string | null;
}

/** `GET /api/v1/me/access`: the caller's own roles, for any authenticated caller. */
export interface MyAccessView {
  readonly mapping_configured: boolean;
  readonly groups_overage: boolean;
  readonly roles: readonly AccessRoleView[];
}

export interface RoleMappingEntryView {
  readonly id: string;
  readonly claim: "roles" | "groups";
  readonly value: string;
  readonly role: string;
  readonly domain_mode: "all" | "explicit";
  readonly domain_ids: readonly string[];
  readonly customer_control: boolean;
}

/** `GET /api/v1/admin/identity/role-mapping`: the effective Entra role mapping, read only. */
export interface RoleMappingView {
  readonly active: boolean;
  readonly tenant_id: string | null;
  readonly audience: string | null;
  readonly cloud: string | null;
  readonly entries: readonly RoleMappingEntryView[];
}
