import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { FederationPage } from "./FederationPage";
import { FEDERATION_ROUTE } from "./paths";

export const federationRoutes: RouteObject[] = [
  { path: FEDERATION_ROUTE, element: <FederationPage /> },
];

/** Navigation is a usability aid only; the API decides access on every request. */
export function federationNavItems(): NavItem[] {
  return [{ to: `/${FEDERATION_ROUTE}`, label: "Federation", permission: "data.read" }];
}
