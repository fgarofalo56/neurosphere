import type { RouteObject } from "react-router";
import { actionsRoutes } from "../features/actions";
import { catalogRoutes } from "../features/catalog";
import { copilotRoutes } from "../features/copilot";
import { dashboardRoutes } from "../features/dashboards";
import { gatewaysRoutes } from "../features/gateways";
import { mapRoutes } from "../features/map";
import { mapTableRoutes } from "../features/map-table";
import { mcpAdminRoutes } from "../features/mcp-admin";
import { replayRoutes } from "../features/replay";
import { reportsRoutes } from "../features/reports";
import { reviewRoutes } from "../features/review";
import { reconciliationRoutes } from "../features/reconciliation";
import { qualityRoutes } from "../features/quality";
import { recommendationRoutes } from "../features/recommendations";
import { sandboxRoutes } from "../features/sandbox";
import { workspaceRoutes } from "../features/workspaces";

/**
 * Every feature route the app registers as a child of the shell layout. The route manifest test
 * (route-manifest.test.ts) walks this list, so a new route must also be added to
 * route-manifest.json, which the accessibility suite reads.
 */
export const appRoutes: readonly RouteObject[] = [
  ...workspaceRoutes,
  ...dashboardRoutes,
  ...reconciliationRoutes,
  ...recommendationRoutes,
  ...qualityRoutes,
  ...actionsRoutes,
  ...gatewaysRoutes,
  ...catalogRoutes,
  ...reviewRoutes,
  ...mapRoutes,
  ...mapTableRoutes,
  ...replayRoutes,
  ...reportsRoutes,
  ...mcpAdminRoutes,
  ...copilotRoutes,
  ...sandboxRoutes,
];
