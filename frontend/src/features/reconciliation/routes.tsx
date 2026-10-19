import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { ReconciliationPage } from "./ReconciliationPage";

export const RECONCILIATION_PATH = "/reconciliation";

export const reconciliationRoutes: RouteObject[] = [
  { path: RECONCILIATION_PATH.replace(/^\//, ""), element: <ReconciliationPage /> },
];

/** Navigation is a usability aid only; the API decides access on every request. */
export function reconciliationNavItems(): NavItem[] {
  return [{ to: RECONCILIATION_PATH, label: "Reconciliation" }];
}
