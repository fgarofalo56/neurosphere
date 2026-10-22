import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { REPORT_VIEW_ROUTE, REPORTS_LIST_ROUTE } from "./paths";
import { ReportsListPage } from "./ReportsListPage";
import { ReportViewPage } from "./ReportViewPage";

export const reportsRoutes: RouteObject[] = [
  { path: REPORTS_LIST_ROUTE, element: <ReportsListPage /> },
  { path: REPORT_VIEW_ROUTE, element: <ReportViewPage /> },
];

/** Navigation is a usability aid only; the API decides access on every request. */
export function reportsNavItems(): NavItem[] {
  return [{ to: `/${REPORTS_LIST_ROUTE}`, label: "Reports" }];
}
