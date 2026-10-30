/**
 * Path constants for the FinOps forecast. Kept free of heavy imports so the app shell can
 * reference routes without loading Fluent UI.
 */
export const FINOPS_API_PREFIX = "/api/v1/finops";

export const FINOPS_FORECAST_ROUTE = "finops/forecast";

export function forecastPath(domain: string): string {
  return `${FINOPS_API_PREFIX}/domains/${encodeURIComponent(domain)}/forecast`;
}
