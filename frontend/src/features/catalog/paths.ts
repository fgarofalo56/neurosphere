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
