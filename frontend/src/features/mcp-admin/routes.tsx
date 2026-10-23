import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { McpServerDetailPage } from "./McpServerDetailPage";
import { McpServersPage } from "./McpServersPage";
import { MCP_ADMIN_LIST_ROUTE, MCP_ADMIN_SERVER_ROUTE } from "./paths";

export const mcpAdminRoutes: RouteObject[] = [
  { path: MCP_ADMIN_LIST_ROUTE, element: <McpServersPage /> },
  { path: MCP_ADMIN_SERVER_ROUTE, element: <McpServerDetailPage /> },
];

/** Navigation is a usability aid only; the API decides access on every request. */
export function mcpAdminNavItems(): NavItem[] {
  return [{ to: `/${MCP_ADMIN_LIST_ROUTE}`, label: "MCP servers", permission: "config.manage" }];
}
