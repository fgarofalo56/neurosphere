import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { ActionDetailPage, ActionsPage } from "./ActionsPage";
import { ProposeSwapPage } from "./ProposeSwapPage";

export const actionsRoutes: RouteObject[] = [
  { path: "actions", element: <ActionsPage /> },
  { path: "actions/detail", element: <ActionDetailPage /> },
  { path: "actions/propose", element: <ProposeSwapPage /> },
];

/** Navigation is a usability aid only; the API decides access on every request. */
export function actionsNavItems(): NavItem[] {
  return [{ to: "/actions", label: "Actions" }];
}
