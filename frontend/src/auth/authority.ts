import type { CloudName } from "./config";

/** Login host per cloud. Government is config-selected, never routed to Commercial. */
export const AUTHORITY_HOSTS: Readonly<Record<CloudName, string>> = {
  commercial: "login.microsoftonline.com",
  government: "login.microsoftonline.us",
};

export interface AuthorityInfo {
  readonly host: string;
  readonly authority: string;
  readonly knownAuthorities: readonly string[];
}

export function resolveAuthority(cloud: CloudName, tenantId: string): AuthorityInfo {
  const host = AUTHORITY_HOSTS[cloud];
  if (host === undefined) {
    throw new Error(`Unsupported cloud: ${String(cloud)}`);
  }
  if (tenantId.trim() === "") {
    throw new Error("tenantId is required");
  }
  return {
    host,
    authority: `https://${host}/${encodeURIComponent(tenantId)}`,
    knownAuthorities: [host],
  };
}
