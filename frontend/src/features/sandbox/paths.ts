/**
 * Path constants for the sandbox feature. The server enforces isolation (container allowlist);
 * the UI toggle only selects which route family the UI shows, it is never the control.
 *
 * Reads need `data.read`; the API answers 403 for anyone else, whatever the nav shows.
 */
export const SANDBOX_API_PREFIX = "/api/v1/sandbox";

export const SANDBOX_ROUTE = "sandbox";

export function sandboxStatusPath(): string {
  return `${SANDBOX_API_PREFIX}/status`;
}

export function sandboxEntitiesPath(): string {
  return `${SANDBOX_API_PREFIX}/entities`;
}
