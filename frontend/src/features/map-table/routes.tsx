import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { MapTablePage } from "./MapTablePage";

export const MAP_TABLE_PATH = "/map/table";

export const mapTableRoutes: RouteObject[] = [
  { path: MAP_TABLE_PATH.replace(/^\//, ""), element: <MapTablePage /> },
];

/** Navigation is a usability aid only; the API decides access on every request. */
export function mapTableNavItems(): NavItem[] {
  return [{ to: MAP_TABLE_PATH, label: "Map table" }];
}
