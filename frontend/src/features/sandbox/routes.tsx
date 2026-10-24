import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { SANDBOX_ROUTE } from "./paths";
import { SandboxPage } from "./SandboxPage";

export const sandboxRoutes: RouteObject[] = [{ path: SANDBOX_ROUTE, element: <SandboxPage /> }];

/** Navigation is a usability aid only; the API decides access on every request. */
export function sandboxNavItems(): NavItem[] {
  return [{ to: `/${SANDBOX_ROUTE}`, label: "Sandbox", permission: "data.read" }];
}
