import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { EvaluationsPage } from "./EvaluationsPage";
import { EVALUATIONS_ROUTE } from "./paths";

export const evaluationsRoutes: RouteObject[] = [
  { path: EVALUATIONS_ROUTE, element: <EvaluationsPage /> },
];

/** Navigation is a usability aid only; the API decides access on every request. */
export function evaluationsNavItems(): NavItem[] {
  return [{ to: `/${EVALUATIONS_ROUTE}`, label: "Evaluation results", permission: "data.read" }];
}
