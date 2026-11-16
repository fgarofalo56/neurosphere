/**
 * Path constants for the admin console (PRP-53). Kept free of heavy imports so the app shell can
 * reference routes without loading Fluent UI.
 *
 * Exact API paths, read from services/api/openapi.json after PRP-39, 40, 44 and 45 merged:
 * - PRP-39 identity:  GET /principals, GET /principals/{id}, PUT|DELETE /principals/{id}/
 *   role-assignments/{assignment_id}, domain-memberships/{domain_id}, grants/{grant_id},
 *   POST|GET|DELETE /principals/{id}/revocation. Writes carry If-Match (the ETag header of the
 *   last read) except the first entry for a new principal.
 * - PRP-44 platform:  GET /domains?include_retired&limit, POST /domains, POST /domains/{id}/retire
 *   (If-Match) under /api/v1/admin/platform.
 * - PRP-45 system:    GET /status, /checklist, /settings under /api/v1/admin/system.
 * - PRP-40 audit:     GET /search, /export, /denials, /siem/status under /api/v1/audit.
 */
export const ADMIN_IDENTITY_API = "/api/v1/admin/identity";
export const ADMIN_PLATFORM_API = "/api/v1/admin/platform";
export const ADMIN_SYSTEM_API = "/api/v1/admin/system";
export const ADMIN_AUDIT_API = "/api/v1/audit";

export const ADMIN_HOME_PATH = "/workspaces/admin";
export const ADMIN_IDENTITY_ROUTE = "admin/identity";
export const ADMIN_PRINCIPAL_ROUTE = "admin/identity/principal";
export const ADMIN_DOMAINS_ROUTE = "admin/domains";
export const ADMIN_SYSTEM_ROUTE = "admin/system";
export const ADMIN_AUDIT_ROUTE = "admin/audit";

/** Detail link: the principal id rides in the query like the other detail pages. */
export function principalHref(principalId: string): string {
  return `/${ADMIN_PRINCIPAL_ROUTE}?${new URLSearchParams({ principal_id: principalId }).toString()}`;
}

function enc(value: string): string {
  return encodeURIComponent(value);
}

export const identityPaths = {
  principals: (): string => `${ADMIN_IDENTITY_API}/principals`,
  principal: (id: string): string => `${ADMIN_IDENTITY_API}/principals/${enc(id)}`,
  role: (id: string, assignmentId: string): string =>
    `${ADMIN_IDENTITY_API}/principals/${enc(id)}/role-assignments/${enc(assignmentId)}`,
  membership: (id: string, domainId: string): string =>
    `${ADMIN_IDENTITY_API}/principals/${enc(id)}/domain-memberships/${enc(domainId)}`,
  grant: (id: string, grantId: string): string =>
    `${ADMIN_IDENTITY_API}/principals/${enc(id)}/grants/${enc(grantId)}`,
  revocation: (id: string): string => `${ADMIN_IDENTITY_API}/principals/${enc(id)}/revocation`,
};

export const platformPaths = {
  domains: (): string => `${ADMIN_PLATFORM_API}/domains`,
  domain: (domainId: string): string => `${ADMIN_PLATFORM_API}/domains/${enc(domainId)}`,
  retire: (domainId: string): string => `${ADMIN_PLATFORM_API}/domains/${enc(domainId)}/retire`,
};

export const systemPaths = {
  status: (): string => `${ADMIN_SYSTEM_API}/status`,
  checklist: (): string => `${ADMIN_SYSTEM_API}/checklist`,
  settings: (): string => `${ADMIN_SYSTEM_API}/settings`,
};

export const auditPaths = {
  search: (): string => `${ADMIN_AUDIT_API}/search`,
  export: (): string => `${ADMIN_AUDIT_API}/export`,
  denials: (): string => `${ADMIN_AUDIT_API}/denials`,
  siem: (): string => `${ADMIN_AUDIT_API}/siem/status`,
};
