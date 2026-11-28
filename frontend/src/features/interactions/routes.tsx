import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { InteractionsPage } from "./InteractionsPage";

export const INTERACTIONS_PATH = "/interactions";

export const interactionsRoutes: RouteObject[] = [
  { path: INTERACTIONS_PATH.replace(/^\//, ""), element: <InteractionsPage /> },
];

/** Navigation is a usability aid only; the API decides access on every request. */
export function interactionsNavItems(): NavItem[] {
  return [{ to: INTERACTIONS_PATH, label: "Interactions" }];
}
