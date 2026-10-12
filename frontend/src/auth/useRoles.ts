import { useMsal } from "@azure/msal-react";
import { parseRoles, rolesLabel, type NsRole } from "./roles";

export interface RolesView {
  readonly roles: readonly NsRole[];
  readonly label: string;
  readonly hasRoles: boolean;
}

/**
 * Reads the ID-token `roles` claim for DISPLAY and navigation visibility only.
 * Claims never grant access; the API decides authorization server-side.
 */
export function useRoles(): RolesView {
  const { instance, accounts } = useMsal();
  const account = instance.getActiveAccount() ?? accounts[0] ?? null;
  const roles = parseRoles(account?.idTokenClaims?.["roles"]);
  return { roles, label: rolesLabel(roles), hasRoles: roles.length > 0 };
}
