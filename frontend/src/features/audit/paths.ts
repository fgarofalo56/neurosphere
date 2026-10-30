/**
 * Path constants for the audit log. Kept free of heavy imports so the app shell can reference
 * routes without loading Fluent UI.
 *
 * The audit page has its own domain list (an auditor holds no data.read, so /me/domains is 403)
 * and keeps the selection in `audit_domain`, never `domain_id`.
 */
export const AUDIT_API_PREFIX = "/api/v1/audit";

export const AUDIT_ROUTE = "audit";
export const AUDIT_DOMAIN_PARAM = "audit_domain";

export function auditDomainsPath(): string {
  return `${AUDIT_API_PREFIX}/domains`;
}

export function auditRecordsPath(domain: string): string {
  return `${auditDomainsPath()}/${encodeURIComponent(domain)}/records`;
}

export function auditVerifyPath(domain: string): string {
  return `${auditDomainsPath()}/${encodeURIComponent(domain)}/verify`;
}
