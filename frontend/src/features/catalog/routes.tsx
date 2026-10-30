import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { CatalogPublicationPage } from "./CatalogPublicationPage";
import { CATALOG_PUBLICATION_ROUTE } from "./paths";

export const catalogRoutes: RouteObject[] = [
  { path: CATALOG_PUBLICATION_ROUTE, element: <CatalogPublicationPage /> },
];

/** Navigation is a usability aid only; the API decides access on every request. */
export function catalogNavItems(): NavItem[] {
  return [{ to: `/${CATALOG_PUBLICATION_ROUTE}`, label: "Publication" }];
}
