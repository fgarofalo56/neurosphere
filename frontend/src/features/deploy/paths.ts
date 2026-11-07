/**
 * Path constants for deployment intelligence. Kept free of heavy imports so the app shell can
 * reference routes without loading Fluent UI.
 *
 * The plan route is a pure function. The apply routes (PRP-08 item 12) only approve a plan, DRAFT
 * an apply intent and preview an uninstall; none of them changes Azure from the browser, and
 * there is no delete path. The domain is a path segment, the authorization target.
 */
export const DEPLOY_API_PREFIX = "/api/v1/deploy";

export const DEPLOY_ROUTE = "deploy";
export const DEPLOY_CAPABILITIES_ROUTE = "deploy/capabilities";

export function deployScanPath(): string {
  return `${DEPLOY_API_PREFIX}/scan`;
}

export function deployPlanPath(): string {
  return `${DEPLOY_API_PREFIX}/plan`;
}

const APPLY_PREFIX = `${DEPLOY_API_PREFIX}/apply/domains`;

export function approvePlanPath(domainId: string): string {
  return `${APPLY_PREFIX}/${encodeURIComponent(domainId)}/plans/approve`;
}

export function applyPlanPath(domainId: string): string {
  return `${APPLY_PREFIX}/${encodeURIComponent(domainId)}/plans/apply`;
}

export function uninstallPreviewPath(domainId: string): string {
  return `${APPLY_PREFIX}/${encodeURIComponent(domainId)}/uninstall/preview`;
}

export function capabilitiesPath(): string {
  return "/api/v1/capabilities";
}
