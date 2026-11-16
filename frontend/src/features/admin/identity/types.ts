/** The PRP-39 shapes the identity pages read (neurosphere_contracts.admin.v1). */
export type RoleName = "viewer" | "analyst" | "domain_steward" | "admin" | "security_auditor";
export const ROLE_NAMES: readonly RoleName[] = [
  "viewer",
  "analyst",
  "domain_steward",
  "admin",
  "security_auditor",
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
