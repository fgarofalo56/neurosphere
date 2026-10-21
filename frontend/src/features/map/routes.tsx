import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { MapPage } from "./MapPage";
import { MAP_PATH } from "./paths";

export { MAP_PATH };

export const mapRoutes: RouteObject[] = [
  { path: MAP_PATH.replace(/^\//, ""), element: <MapPage /> },
];

/** Navigation is a usability aid only; the API decides access on every request. */
export function mapNavItems(): NavItem[] {
  return [{ to: MAP_PATH, label: "Map" }];
}
