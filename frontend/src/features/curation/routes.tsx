import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { EdgePage } from "./EdgePage";
import { CURATION_EDGE_ROUTE } from "./paths";

export const curationRoutes: RouteObject[] = [{ path: CURATION_EDGE_ROUTE, element: <EdgePage /> }];

/** Navigation is a usability aid only; the API decides access on every request. */
export function curationNavItems(): NavItem[] {
  return [
    // Reached from the entity lineage tab; deliberately not in the nav.
  ];
}
