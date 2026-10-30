import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { AuditPage } from "./AuditPage";
import { AUDIT_ROUTE } from "./paths";

export const auditRoutes: RouteObject[] = [{ path: AUDIT_ROUTE, element: <AuditPage /> }];

/** Navigation is a usability aid only; the API decides access on every request. */
export function auditNavItems(): NavItem[] {
  return [{ to: `/${AUDIT_ROUTE}`, label: "Audit log", roles: ["Auditor", "Admin"] }];
}
