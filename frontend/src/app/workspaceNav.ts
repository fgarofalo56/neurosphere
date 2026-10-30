import { useMemo } from "react";
// The shell and nav import ONLY light route modules (`paths.ts` / `routes.tsx`), never a feature
// `index.ts`: those pull in the WebGL map renderer and the chart sandbox, which crash jsdom.
import { actionsNavItems } from "../features/actions/routes";
import { catalogNavItems } from "../features/catalog/routes";
import { dashboardNavItems } from "../features/dashboards/routes";
import { gatewaysNavItems } from "../features/gateways/routes";
import { MAP_PATH } from "../features/map/paths";
import { MAP_TABLE_PATH } from "../features/map-table/paths";
import { mcpAdminNavItems } from "../features/mcp-admin/routes";
import { OVERVIEW_PATH } from "../features/overview/paths";
import { qualityNavItems } from "../features/quality/routes";
import { reconciliationNavItems } from "../features/reconciliation/routes";
import { recommendationNavItems } from "../features/recommendations/routes";
import { replayNavItems } from "../features/replay/routes";
import { REPORTS_LIST_ROUTE } from "../features/reports/paths";
import { reviewNavItems } from "../features/review/routes";
import { sandboxNavItems } from "../features/sandbox/routes";
import { useSandboxStore } from "../features/sandbox/store";
import { WORKSPACES } from "../features/workspaces/personas";
import type { NavGroup, NavItem } from "./navigation";

function inGroup(group: NavGroup, items: readonly NavItem[]): NavItem[] {
  return items.map((item) => ({ ...item, group }));
}

/**
 * Navigation entries, grouped. Roles come from claims and only suggest which workspaces to show;
 * hiding an entry is NOT authorization, the API decides. Feature entries are always listed: the
 * pages call the API, which answers 403 for a domain the caller cannot read.
 */
export function buildAppNavItems(): readonly NavItem[] {
  return [
    { to: OVERVIEW_PATH, label: "Home", group: "Overview" },
    ...WORKSPACES.map((def): NavItem => ({
      to: def.path,
      label: def.label,
      group: "Overview",
      roles: [def.persona],
    })),
    ...inGroup("Cost & usage", [...dashboardNavItems(), ...reconciliationNavItems()]),
    ...inGroup("Agents", [
      { to: MAP_PATH, label: "Map" },
      { to: MAP_TABLE_PATH, label: "Map table" },
      ...replayNavItems(),
    ]),
    ...inGroup("Quality", [...qualityNavItems(), ...recommendationNavItems()]),
    ...inGroup("Governance", [
      ...reviewNavItems(),
      ...actionsNavItems(),
      ...gatewaysNavItems(),
      ...catalogNavItems(),
      // Cosmetic: the API requires config.manage on every MCP admin route.
      ...mcpAdminNavItems(),
    ]),
    ...inGroup("Reports", [{ to: `/${REPORTS_LIST_ROUTE}`, label: "Reports" }]),
  ];
}

/**
 * Hook form for `createAppRoutes({ useNavItems })`; the list is stable across renders. The
 * sandbox entry is listed only while sandbox mode is on. That is UX only: the route stays
 * registered and the API enforces access and isolation.
 */
export function useAppNavItems(): readonly NavItem[] {
  const base = useMemo(buildAppNavItems, []);
  const sandbox = useSandboxStore((s) => s.enabled);
  return useMemo(
    () => (sandbox ? [...base, ...inGroup("Overview", sandboxNavItems())] : base),
    [base, sandbox],
  );
}
