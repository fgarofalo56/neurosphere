import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { ReviewItemPage } from "./ReviewItemPage";
import { ReviewQueuePage } from "./ReviewQueuePage";

export const reviewRoutes: RouteObject[] = [
  { path: "review", element: <ReviewQueuePage /> },
  { path: "review/item", element: <ReviewItemPage /> },
];

/** Navigation is a usability aid only; the API decides access on every request. */
export function reviewNavItems(): NavItem[] {
  return [{ to: "/review", label: "Review" }];
}
