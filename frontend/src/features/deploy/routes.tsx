import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { CapabilitiesPage } from "./CapabilitiesPage";
import { DeployPage } from "./DeployPage";
import { DEPLOY_CAPABILITIES_ROUTE, DEPLOY_ROUTE } from "./paths";

export const deployRoutes: RouteObject[] = [
  { path: DEPLOY_ROUTE, element: <DeployPage /> },
  { path: DEPLOY_CAPABILITIES_ROUTE, element: <CapabilitiesPage /> },
];

/** Navigation is a usability aid only; the API decides access on every request. */
export function deployNavItems(): NavItem[] {
  return [
    { to: `/${DEPLOY_ROUTE}`, label: "Deployment", permission: "config.manage" },
    { to: `/${DEPLOY_CAPABILITIES_ROUTE}`, label: "Capabilities", permission: "config.manage" },
  ];
}
