import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { AuditPlaceholderPage } from "./PlaceholderPage";
import { AUDIT_ROUTE } from "./paths";

export const auditRoutes: RouteObject[] = [
  { path: AUDIT_ROUTE, element: <AuditPlaceholderPage /> },
];

/** Navigation is a usability aid only; the API decides access on every request. */
export function auditNavItems(): NavItem[] {
  return [{ to: `/${AUDIT_ROUTE}`, label: "Audit log", roles: ["Auditor", "Admin"] }];
}
