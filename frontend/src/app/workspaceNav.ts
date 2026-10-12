import { useRoles } from "../auth";
import { workspaceNavItems } from "../features/workspaces";
import type { NavItem } from "./routes";

/**
 * Navigation entries for the signed-in user. Roles come from claims and only
 * suggest which workspaces to show; hiding an entry is NOT authorization,
 * the API decides.
 */
export function useAppNavItems(): readonly NavItem[] {
  const { roles } = useRoles();
  return [{ to: "/", label: "Home" }, ...workspaceNavItems(roles)];
}
