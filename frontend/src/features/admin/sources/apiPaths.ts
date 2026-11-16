/**
 * API paths the PRP-57 admin pages call, with the PRP that ships each. Read from
 * services/api/openapi.json on main after PRP-41, 42, 44 and 45 merged.
 *
 * Differences from the PRP-57 text (the PRP marked the PRP-44 paths UNVERIFIED):
 * - PRP-44 platform routes: price sheets are `/api/v1/admin/platform/price-sheets` (POST uploads,
 *   GET lists versions, `/{snapshot_id}/coverage` reads coverage); budgets are
 *   `/api/v1/admin/platform/budgets[/{budget_id}]` (POST, GET, PUT and DELETE with If-Match); the
 *   review policy is a single document `GET|PUT /api/v1/admin/platform/review-policy` (If-Match).
 *   There is no "active" flag on a price sheet version; the page marks the newest effective date.
 * - PRP-45 settings: `GET /settings` and `GET|PUT /settings/{key}`; a write sends the document
 *   ETag in If-Match and the SystemSetting body (the key `write_targets` uses setting_key
 *   `write_target`).
 * - PRP-41: producers carry `sources` as a map of source id to observation kind, not a free list.
 */
export const SOURCES_API = "/api/v1/admin/sources";
export const PLATFORM_API = "/api/v1/admin/platform";
export const SETTINGS_API = "/api/v1/admin/system/settings";

export const ADMIN_PRODUCERS_ROUTE = "admin/sources/producers";
export const ADMIN_CONNECTORS_ROUTE = "admin/sources/connectors";
export const ADMIN_GATEWAYS_ROUTE = "admin/gateways";
export const ADMIN_CATALOG_IMPORT_ROUTE = "admin/catalog-import";
export const ADMIN_PRICING_ROUTE = "admin/pricing";
export const ADMIN_FEATURES_ROUTE = "admin/features";
export const ADMIN_REVIEW_POLICY_ROUTE = "admin/review-policy";

function enc(value: string): string {
  return encodeURIComponent(value);
}

/** PRP-41 producers. */
export const producerPaths = {
  list: (): string => `${SOURCES_API}/producers`,
  one: (id: string): string => `${SOURCES_API}/producers/${enc(id)}`,
  rotate: (id: string): string => `${SOURCES_API}/producers/${enc(id)}/rotate`,
  disable: (id: string): string => `${SOURCES_API}/producers/${enc(id)}/disable`,
  enable: (id: string): string => `${SOURCES_API}/producers/${enc(id)}/enable`,
};

/** PRP-42 connector configurations. */
export const connectorPaths = {
  list: (): string => `${SOURCES_API}/connectors`,
  one: (id: string): string => `${SOURCES_API}/connectors/${enc(id)}`,
  enable: (id: string): string => `${SOURCES_API}/connectors/${enc(id)}/enable`,
  disable: (id: string): string => `${SOURCES_API}/connectors/${enc(id)}/disable`,
};

/** PRP-44 pricing, budgets and review policy. */
export const pricingPaths = {
  priceSheets: (): string => `${PLATFORM_API}/price-sheets`,
  budgets: (): string => `${PLATFORM_API}/budgets`,
  budget: (id: string): string => `${PLATFORM_API}/budgets/${enc(id)}`,
  reviewPolicy: (): string => `${PLATFORM_API}/review-policy`,
};

/** PRP-45 stored runtime settings. */
export const settingPaths = {
  list: (): string => SETTINGS_API,
  one: (key: string): string => `${SETTINGS_API}/${enc(key)}`,
};

/** Existing routes. */
export const existingPaths = {
  gateways: (domain: string): string => `/api/v1/gateways/domains/${enc(domain)}/gateways`,
  catalogImport: (): string => "/api/v1/catalog/import",
  myDomains: (): string => "/api/v1/me/domains",
};
