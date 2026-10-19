import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { RecommendationDetailPage } from "./RecommendationDetailPage";
import { RecommendationListPage } from "./RecommendationListPage";

export const recommendationRoutes: RouteObject[] = [
  { path: "recommendations", element: <RecommendationListPage /> },
  { path: "recommendations/detail", element: <RecommendationDetailPage /> },
];

/** Navigation is a usability aid only; the API decides access on every request. */
export function recommendationNavItems(): NavItem[] {
  return [{ to: "/recommendations", label: "Recommendations" }];
}
