/**
 * Path constants for the catalog publication feature (Grants and MCP servers). Kept free of heavy
 * imports so the app shell can reference routes without loading Fluent UI.
 *
 * The publish and unpublish routes only DRAFT action intents (`action.propose` in the entity's
 * domain); the one action executor applies them after confirmation and approval.
 */
export const CATALOG_API_PREFIX = "/api/v1/catalog";

export const CATALOG_PUBLICATION_ROUTE = "catalog/publication";

export function entitiesPath(): string {
  return `${CATALOG_API_PREFIX}/entities`;
}

export function grantActionPath(entityId: string, action: "publish" | "unpublish"): string {
  return `${CATALOG_API_PREFIX}/grants/${encodeURIComponent(entityId)}/${action}`;
}

export function mcpServerPath(entityId: string): string {
  return `${CATALOG_API_PREFIX}/mcp-servers/${encodeURIComponent(entityId)}`;
}

export function mcpPublicationPath(entityId: string): string {
  return `${mcpServerPath(entityId)}/publication`;
}

export function mcpActionPath(entityId: string, action: "publish" | "unpublish"): string {
  return `${mcpServerPath(entityId)}/${action}`;
}

// ---- PRP-31: catalog explorer. Domain-path adapters stand in for the domain_id query routes,
// which ApiClient forbids. Ids go through encodeURIComponent.
export const CATALOG_EXPLORER_ROUTE = "catalog";
export const CATALOG_ENTITY_ROUTE = "catalog/entity";
export const CATALOG_RECERTIFICATIONS_ROUTE = "catalog/recertifications";
export const CATALOG_STALE_AGENTS_ROUTE = "catalog/stale-agents";

export function domainEntitiesPath(domain: string): string {
  return `${CATALOG_API_PREFIX}/domains/${encodeURIComponent(domain)}/entities`;
}

export function domainSearchPath(domain: string): string {
  return `${CATALOG_API_PREFIX}/domains/${encodeURIComponent(domain)}/search`;
}

export function domainExportPath(domain: string): string {
  return `${CATALOG_API_PREFIX}/domains/${encodeURIComponent(domain)}/export`;
}

export function entityPath(entityId: string): string {
  return `${entitiesPath()}/${encodeURIComponent(entityId)}`;
}

export function entityDeprecatePath(entityId: string): string {
  return `${entityPath(entityId)}/deprecate`;
}

export function entityRecertifyPath(entityId: string): string {
  return `${entityPath(entityId)}/recertify`;
}

export function lineageNeighborsPath(): string {
  return `${CATALOG_API_PREFIX}/lineage/neighbors`;
}

export function lineageImpactPath(): string {
  return `${CATALOG_API_PREFIX}/lineage/impact`;
}

export function recertificationsPath(): string {
  return `${CATALOG_API_PREFIX}/recertifications`;
}

export function staleAgentsDryRunPath(): string {
  return `${CATALOG_API_PREFIX}/reconcile/stale-agents/dry-run`;
}

export function staleAgentsConfirmPath(): string {
  return `${CATALOG_API_PREFIX}/reconcile/stale-agents/confirm`;
}

/** App route (not API) of one entity; the page reads `entity_id` from it. */
export function entityHref(entityId: string): string {
  const p = new URLSearchParams({ entity_id: entityId });
  return `/${CATALOG_ENTITY_ROUTE}?${p.toString()}`;
}
