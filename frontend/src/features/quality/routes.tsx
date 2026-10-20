import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { QualityPage } from "./QualityPage";

export const qualityRoutes: RouteObject[] = [{ path: "quality", element: <QualityPage /> }];

/** Navigation is a usability aid only; the API decides access on every request. */
export function qualityNavItems(): NavItem[] {
  return [{ to: "/quality", label: "Quality" }];
}
