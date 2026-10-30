import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { GatewaysPage } from "./GatewaysPage";
import { GATEWAYS_ROUTE } from "./paths";

export const gatewaysRoutes: RouteObject[] = [{ path: GATEWAYS_ROUTE, element: <GatewaysPage /> }];

/** Navigation is a usability aid only; the API decides access on every request. */
export function gatewaysNavItems(): NavItem[] {
  return [{ to: `/${GATEWAYS_ROUTE}`, label: "Gateways" }];
}
