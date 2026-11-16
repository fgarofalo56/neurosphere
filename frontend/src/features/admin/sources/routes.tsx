import type { RouteObject } from "react-router";
import type { NavItem } from "../../../app/routes";
import { CatalogImportPage } from "../catalog-import/CatalogImportPage";
import { FeatureSettingsPage } from "../features/FeatureSettingsPage";
import { RegisterGatewayPage } from "../gateways/RegisterGatewayPage";
import { PricingPage } from "../pricing/PricingPage";
import { ReviewPolicyPage } from "../review-policy/ReviewPolicyPage";
import {
  ADMIN_CATALOG_IMPORT_ROUTE,
  ADMIN_CONNECTORS_ROUTE,
  ADMIN_FEATURES_ROUTE,
  ADMIN_GATEWAYS_ROUTE,
  ADMIN_PRICING_ROUTE,
  ADMIN_PRODUCERS_ROUTE,
  ADMIN_REVIEW_POLICY_ROUTE,
} from "./apiPaths";
import { ConnectorsPage } from "./ConnectorsPage";
import { ProducersPage } from "./ProducersPage";

/** Admin console part 2 (PRP-57): data sources, pricing and feature settings. */
export const adminSourcesRoutes: RouteObject[] = [
  { path: ADMIN_PRODUCERS_ROUTE, element: <ProducersPage /> },
  { path: ADMIN_CONNECTORS_ROUTE, element: <ConnectorsPage /> },
  { path: ADMIN_GATEWAYS_ROUTE, element: <RegisterGatewayPage /> },
  { path: ADMIN_CATALOG_IMPORT_ROUTE, element: <CatalogImportPage /> },
  { path: ADMIN_PRICING_ROUTE, element: <PricingPage /> },
  { path: ADMIN_FEATURES_ROUTE, element: <FeatureSettingsPage /> },
  { path: ADMIN_REVIEW_POLICY_ROUTE, element: <ReviewPolicyPage /> },
];

/**
 * Navigation entries come from `ADMIN_AREAS` (PRP-53 `adminCoreNavItems` maps every area, and
 * this PRP appended its areas there), so adding them here would list each page twice. The
 * function exists so a shell that wants a separate group can adopt it without a new module.
 */
export function adminSourcesNavItems(): NavItem[] {
  return [];
}
