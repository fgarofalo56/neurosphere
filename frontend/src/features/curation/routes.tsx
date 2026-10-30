import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { CurationPlaceholderPage } from "./PlaceholderPage";
import { CURATION_EDGE_ROUTE } from "./paths";

export const curationRoutes: RouteObject[] = [
  { path: CURATION_EDGE_ROUTE, element: <CurationPlaceholderPage /> },
];

/** Navigation is a usability aid only; the API decides access on every request. */
export function curationNavItems(): NavItem[] {
  return [
    // Reached from the entity lineage tab; deliberately not in the nav.
  ];
}
