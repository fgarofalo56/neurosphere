import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { MapTablePage } from "./MapTablePage";
import { MAP_TABLE_PATH } from "./paths";

export { MAP_TABLE_PATH };

export const mapTableRoutes: RouteObject[] = [
  { path: MAP_TABLE_PATH.replace(/^\//, ""), element: <MapTablePage /> },
];

/** Navigation is a usability aid only; the API decides access on every request. */
export function mapTableNavItems(): NavItem[] {
  return [{ to: MAP_TABLE_PATH, label: "Map table" }];
}
