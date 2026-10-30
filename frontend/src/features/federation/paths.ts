/**
 * Path constants for federated summaries. Kept free of heavy imports so the app shell can
 * reference routes without loading Fluent UI.
 */
export const FEDERATION_API_PREFIX = "/api/v1/federation";

export const FEDERATION_ROUTE = "federation";

export function federationSummaryPath(): string {
  return `${FEDERATION_API_PREFIX}/summary`;
}

export function federationCellSummaryPath(): string {
  return `${FEDERATION_API_PREFIX}/cell-summary`;
}
