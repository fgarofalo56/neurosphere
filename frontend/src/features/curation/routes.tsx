import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { EdgePage } from "./EdgePage";
import { CURATION_EDGE_ROUTE, CURATION_REVIEW_QUEUE_ROUTE } from "./paths";
import { ReviewQueuePage } from "./ReviewQueuePage";

export const curationRoutes: RouteObject[] = [
  { path: CURATION_EDGE_ROUTE, element: <EdgePage /> },
  { path: CURATION_REVIEW_QUEUE_ROUTE, element: <ReviewQueuePage /> },
];

/** Navigation is a usability aid only; the API decides access on every request. */
export function curationNavItems(): NavItem[] {
  return [
    // Reached from the entity lineage tab; deliberately not in the nav.
  ];
}

/** Steward queue for the Governance group (cosmetic; the API enforces catalog.curate). */
export function reviewQueueNavItems(): NavItem[] {
  return [
    {
      to: `/${CURATION_REVIEW_QUEUE_ROUTE}`,
      label: "Relationship review",
      permission: "catalog.curate",
    },
  ];
}
