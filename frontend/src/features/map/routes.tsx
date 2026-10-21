import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { MapPage } from "./MapPage";

export const MAP_PATH = "/map";

export const mapRoutes: RouteObject[] = [
  { path: MAP_PATH.replace(/^\//, ""), element: <MapPage /> },
];

/** Navigation is a usability aid only; the API decides access on every request. */
export function mapNavItems(): NavItem[] {
  return [{ to: MAP_PATH, label: "Map" }];
}
