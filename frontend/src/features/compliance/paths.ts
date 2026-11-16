/**
 * Path constants for the compliance evidence pages (PRP-56). Kept free of heavy imports so the
 * app shell can reference routes without loading Fluent UI.
 *
 * An auditor holds no data.read, so the domain list is the audit adapter's own; the selection
 * lives in `compliance_domain`, never `domain_id`.
 */
export const COMPLIANCE_API_PREFIX = "/api/v1/compliance";

export const COMPLIANCE_ROUTE = "compliance";
export const COMPLIANCE_CONTROL_ROUTE = "compliance/control";
export const COMPLIANCE_DOMAIN_PARAM = "compliance_domain";
export const COMPLIANCE_FRAMEWORK_PARAM = "framework";
export const COMPLIANCE_CONTROL_PARAM = "control";

export function frameworksPath(): string {
  return `${COMPLIANCE_API_PREFIX}/frameworks`;
}

export function bundlePath(domain: string): string {
  return `${COMPLIANCE_API_PREFIX}/domains/${encodeURIComponent(domain)}/bundle`;
}

export function controlLink(domain: string, frameworkId: string, controlId: string): string {
  const params = new URLSearchParams({
    [COMPLIANCE_DOMAIN_PARAM]: domain,
    [COMPLIANCE_FRAMEWORK_PARAM]: frameworkId,
    [COMPLIANCE_CONTROL_PARAM]: controlId,
  });
  return `/${COMPLIANCE_CONTROL_ROUTE}?${params.toString()}`;
}
