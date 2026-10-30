/**
 * Path constants for relationship curation. Kept free of heavy imports so the app shell can
 * reference routes without loading Fluent UI.
 *
 * Edge ids contain ":" and may contain "/", so every id goes through encodeURIComponent. The page
 * never sends actor, domain_id or customer_id in a body or query: decisions use the domain-path
 * adapter, which stamps them server-side.
 */
export const CURATION_API_PREFIX = "/api/v1/catalog";

export const CURATION_EDGE_ROUTE = "catalog/edge";

export function edgePath(edgeId: string): string {
  return `${CURATION_API_PREFIX}/curation/edges/${encodeURIComponent(edgeId)}`;
}

/** Domain-path read adapter: the edge plus the version/etag the next decision must quote. */
export function domainEdgePath(domain: string, edgeId: string): string {
  return (
    `${CURATION_API_PREFIX}/domains/${encodeURIComponent(domain)}` +
    `/curation/edges/${encodeURIComponent(edgeId)}`
  );
}

export function edgeOverridesPath(edgeId: string): string {
  return `${edgePath(edgeId)}/overrides`;
}

export function edgeObservationsPath(edgeId: string): string {
  return `${edgePath(edgeId)}/observations`;
}

export function edgeDecisionsPath(domain: string, edgeId: string): string {
  return (
    `${CURATION_API_PREFIX}/domains/${encodeURIComponent(domain)}` +
    `/curation/edges/${encodeURIComponent(edgeId)}/decisions`
  );
}

/** App route (not API) of one edge; the page reads `edge_id` from it. */
export function edgeHref(edgeId: string): string {
  const p = new URLSearchParams({ edge_id: edgeId });
  return `/${CURATION_EDGE_ROUTE}?${p.toString()}`;
}
