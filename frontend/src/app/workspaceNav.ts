import { useRoles } from "../auth";
import { actionsNavItems } from "../features/actions";
import { dashboardNavItems } from "../features/dashboards";
import { mapNavItems } from "../features/map";
import { mapTableNavItems } from "../features/map-table";
import { replayNavItems } from "../features/replay";
import { reviewNavItems } from "../features/review";
import { reconciliationNavItems } from "../features/reconciliation";
import { qualityNavItems } from "../features/quality";
import { recommendationNavItems } from "../features/recommendations";
import { workspaceNavItems } from "../features/workspaces";
import type { NavItem } from "./routes";

/**
 * Navigation entries for the signed-in user. Roles come from claims and only
 * suggest which workspaces to show; hiding an entry is NOT authorization,
 * the API decides.
 */
export function useAppNavItems(): readonly NavItem[] {
  const { roles } = useRoles();
  return [
    { to: "/", label: "Home" },
    ...workspaceNavItems(roles),
    // Always listed: the pages call the API, which answers 403 for a domain the caller cannot read.
    ...dashboardNavItems(),
    ...reconciliationNavItems(),
    ...recommendationNavItems(),
    ...qualityNavItems(),
    ...actionsNavItems(),
    ...reviewNavItems(),
    ...mapNavItems(),
    ...mapTableNavItems(),
    ...replayNavItems(),
  ];
}
