/**
 * Path constants for the MCP administration feature. Kept free of heavy imports so the app shell
 * can reference routes without loading Fluent UI.
 *
 * Every call needs `config.manage`; the API answers 403 for anyone else, whatever the nav shows.
 */
export const MCP_ADMIN_API_PREFIX = "/api/v1/mcp/admin";

export const MCP_ADMIN_LIST_ROUTE = "mcp-admin";
export const MCP_ADMIN_SERVER_ROUTE = "mcp-admin/server";

export function mcpServersPath(): string {
  return `${MCP_ADMIN_API_PREFIX}/servers`;
}

export function mcpServerPath(serverId: string): string {
  return `${mcpServersPath()}/${encodeURIComponent(serverId)}`;
}

export function mcpServerSyncPath(serverId: string): string {
  return `${mcpServerPath(serverId)}/sync`;
}

export function mcpServerToolsPath(serverId: string): string {
  return `${mcpServerPath(serverId)}/tools`;
}

export function mcpToolApprovalPath(serverId: string, toolName: string): string {
  return `${mcpServerToolsPath(serverId)}/${encodeURIComponent(toolName)}/approval`;
}

/** App route (not API) of one server; the page reads `server_id` from it. */
export function mcpServerHref(serverId: string): string {
  const p = new URLSearchParams({ server_id: serverId });
  return `/${MCP_ADMIN_SERVER_ROUTE}?${p.toString()}`;
}
