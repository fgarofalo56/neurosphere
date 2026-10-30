import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { ExecutionControlPage } from "./ExecutionControlPage";
import { EXECUTION_CONTROL_ROUTE } from "./paths";

export const executionControlRoutes: RouteObject[] = [
  { path: EXECUTION_CONTROL_ROUTE, element: <ExecutionControlPage /> },
];

/** Navigation is a usability aid only; the API decides access on every request. */
export function executionControlNavItems(): NavItem[] {
  return [
    { to: `/${EXECUTION_CONTROL_ROUTE}`, label: "Execution control", permission: "config.manage" },
  ];
}
