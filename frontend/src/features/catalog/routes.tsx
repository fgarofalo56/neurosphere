import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { CatalogPublicationPage } from "./CatalogPublicationPage";
import { CatalogEntityPage } from "./CatalogEntityPage";
import { CatalogExplorerPage } from "./CatalogExplorerPage";
import { RecertificationsPage } from "./RecertificationsPage";
import { StaleAgentsPage } from "./StaleAgentsPage";
import {
  CATALOG_ENTITY_ROUTE,
  CATALOG_EXPLORER_ROUTE,
  CATALOG_PUBLICATION_ROUTE,
  CATALOG_RECERTIFICATIONS_ROUTE,
  CATALOG_STALE_AGENTS_ROUTE,
} from "./paths";

/** PRP-31 explorer routes . */
export const catalogExplorerRoutes: RouteObject[] = [
  { path: CATALOG_EXPLORER_ROUTE, element: <CatalogExplorerPage /> },
  { path: CATALOG_ENTITY_ROUTE, element: <CatalogEntityPage /> },
  { path: CATALOG_RECERTIFICATIONS_ROUTE, element: <RecertificationsPage /> },
  { path: CATALOG_STALE_AGENTS_ROUTE, element: <StaleAgentsPage /> },
];

export const catalogRoutes: RouteObject[] = [
  { path: CATALOG_PUBLICATION_ROUTE, element: <CatalogPublicationPage /> },
];

/** Navigation is a usability aid only; the API decides access on every request. */
export function catalogNavItems(): NavItem[] {
  return [{ to: `/${CATALOG_PUBLICATION_ROUTE}`, label: "Publication" }];
}

/** "Catalog" entry for the Agents group. */
export function catalogExplorerNavItems(): NavItem[] {
  return [{ to: `/${CATALOG_EXPLORER_ROUTE}`, label: "Catalog", permission: "data.read" }];
}

/** Curator queues for the Governance group (cosmetic; the API enforces catalog.curate). */
export function catalogGovernanceNavItems(): NavItem[] {
  return [
    {
      to: `/${CATALOG_RECERTIFICATIONS_ROUTE}`,
      label: "Recertifications",
      permission: "catalog.curate",
    },
    { to: `/${CATALOG_STALE_AGENTS_ROUTE}`, label: "Stale agents", permission: "catalog.curate" },
  ];
}
