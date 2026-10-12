import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import type { NsRole } from "../../auth/roles";
import { WorkspacePage } from "./WorkspacePage";
import { WORKSPACES } from "./personas";

export const workspaceRoutes: RouteObject[] = WORKSPACES.map((def) => ({
  path: def.path.replace(/^\//, ""),
  element: <WorkspacePage def={def} />,
}));

/**
 * Nav entries suggested by display roles. Hidden navigation is NOT authorization: it is a
 * usability aid driven by claims. Every route stays registered and every page still calls the
 * API, which is the only place access is decided.
 */
export function workspaceNavItems(roles: readonly NsRole[]): NavItem[] {
  return WORKSPACES.filter((def) => roles.includes(def.persona)).map((def) => ({
    to: def.path,
    label: def.label,
  }));
}
