/**
 * Path constants for deployment intelligence. Kept free of heavy imports so the app shell can
 * reference routes without loading Fluent UI.
 *
 * There is no apply or provision path: the plan is a pure function and provisioning stays the
 * operator-approved IaC pipeline.
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

export function capabilitiesPath(): string {
  return "/api/v1/capabilities";
}
