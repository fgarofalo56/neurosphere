/**
 * The runtime config the CI-mode browser run serves for `/config.json` (PRP-38 item 6). The
 * tenant and scope match the constants in tests/integration/real_stack/serve_stand_in_api.py:
 * the stand-in API accepts tokens for that tenant and audience only. All values are synthetic
 * and non-secret. Never used outside `NS_REAL_STACK_MODE=ci`.
 */
export const STAND_IN_TENANT = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0";
export const STAND_IN_AUDIENCE = "api://neurosphere-real-stack-browser";

export interface StandInConfig {
  readonly cloud: "commercial";
  readonly tenantId: string;
  readonly clientId: string;
  readonly apiBaseUrl: string;
  readonly apiScope: string;
}

export function standInConfig(): StandInConfig {
  return {
    cloud: "commercial",
    tenantId: STAND_IN_TENANT,
    clientId: "00000000-0000-4000-8000-000000000038",
    apiBaseUrl: "/",
    apiScope: STAND_IN_AUDIENCE,
  };
}
