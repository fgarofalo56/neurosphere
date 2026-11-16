import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { CompliancePage } from "./CompliancePage";
import { ControlDetailPage } from "./ControlDetailPage";
import { COMPLIANCE_CONTROL_ROUTE, COMPLIANCE_ROUTE } from "./paths";

export const complianceRoutes: RouteObject[] = [
  { path: COMPLIANCE_ROUTE, element: <CompliancePage /> },
  { path: COMPLIANCE_CONTROL_ROUTE, element: <ControlDetailPage /> },
];

/** Navigation is a usability aid only; the API decides access on every request. */
export function complianceNavItems(): NavItem[] {
  return [{ to: `/${COMPLIANCE_ROUTE}`, label: "Compliance evidence", roles: ["Auditor"] }];
}
