import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { DashboardPage } from "./DashboardPage";
import type { DashboardMetric } from "./types";

export interface DashboardDef {
  readonly path: string;
  readonly label: string;
  readonly metrics: readonly DashboardMetric[];
}

export const DASHBOARDS: readonly DashboardDef[] = [
  { path: "/dashboards/cost", label: "Cost", metrics: ["cost"] },
  { path: "/dashboards/latency", label: "Latency", metrics: ["latency", "errors"] },
  { path: "/dashboards/coverage", label: "Coverage", metrics: ["coverage"] },
];

export const dashboardRoutes: RouteObject[] = DASHBOARDS.map((def) => ({
  path: def.path.replace(/^\//, ""),
  element: <DashboardPage title={def.label} metrics={def.metrics} />,
}));

/** Navigation is a usability aid only; the API decides access on every request. */
export function dashboardNavItems(): NavItem[] {
  return DASHBOARDS.map((def) => ({ to: def.path, label: `${def.label} dashboard` }));
}
