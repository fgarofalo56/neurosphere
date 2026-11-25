import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { AdminAuditPage } from "./audit/AdminAuditPage";
import { CapturePage } from "./capture/CapturePage";
import { ADMIN_CAPTURE_ROUTE } from "./capture/paths";
import { DomainsPage } from "./domains/DomainsPage";
import { PrincipalDetailPage } from "./identity/PrincipalDetailPage";
import { PrincipalsPage } from "./identity/PrincipalsPage";
import {
  ADMIN_AUDIT_ROUTE,
  ADMIN_DOMAINS_ROUTE,
  ADMIN_IDENTITY_ROUTE,
  ADMIN_PRINCIPAL_ROUTE,
  ADMIN_SYSTEM_ROUTE,
} from "./shared/adminPaths";
import { ADMIN_AREAS } from "./shared/areas";
import { SystemPage } from "./system/SystemPage";

/** Admin console routes (PRP-53). The pages call the API, which decides every request. */
export const adminCoreRoutes: RouteObject[] = [
  { path: ADMIN_IDENTITY_ROUTE, element: <PrincipalsPage /> },
  { path: ADMIN_PRINCIPAL_ROUTE, element: <PrincipalDetailPage /> },
  { path: ADMIN_DOMAINS_ROUTE, element: <DomainsPage /> },
  { path: ADMIN_SYSTEM_ROUTE, element: <SystemPage /> },
  { path: ADMIN_AUDIT_ROUTE, element: <AdminAuditPage /> },
  // PRP-103 item 5: read-only interaction capture.
  { path: ADMIN_CAPTURE_ROUTE, element: <CapturePage /> },
];

/**
 * Navigation is a usability aid only (the `roles` hint is cosmetic); the API decides access on
 * every request.
 */
export function adminCoreNavItems(): NavItem[] {
  return ADMIN_AREAS.map((area) => ({
    to: area.to,
    label: `Admin: ${area.label}`,
    roles: area.roles,
  }));
}
