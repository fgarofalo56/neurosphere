/**
 * Path constants for the gateway manage feature. Kept free of heavy imports so the app shell can
 * reference routes without loading Fluent UI.
 *
 * The domain is the addressed resource (a path segment), never a query or body field: the shared
 * client refuses `domain_id` there and the server authorizes the domain against the token scope.
 */
export const GATEWAYS_API_PREFIX = "/api/v1/gateways";

export const GATEWAYS_ROUTE = "gateways";

export function gatewaysPath(domainId: string): string {
  return `${GATEWAYS_API_PREFIX}/domains/${encodeURIComponent(domainId)}/gateways`;
}

export const GATEWAY_DETAIL_ROUTE = "gateways/detail";

/** Detail link: the domain and gateway ride in the query like the other detail pages. */
export function gatewayDetailHref(domainId: string, gatewayId: string): string {
  const params = new URLSearchParams({ domain_id: domainId, gateway_id: gatewayId });
  return `/${GATEWAY_DETAIL_ROUTE}?${params.toString()}`;
}

export function gatewayPath(domainId: string, gatewayId: string): string {
  return `${gatewaysPath(domainId)}/${encodeURIComponent(gatewayId)}`;
}

export function gatewayInventoryPath(domainId: string, gatewayId: string): string {
  return `${gatewayPath(domainId, gatewayId)}/inventory`;
}

export function gatewayModePath(domainId: string, gatewayId: string): string {
  return `${gatewaysPath(domainId)}/${encodeURIComponent(gatewayId)}/mode`;
}
