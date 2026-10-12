/**
 * Fake MSAL instance for the e2e build only (C12: no tenant, no Azure calls).
 * The integrator wires it in main.tsx when `import.meta.env.MODE === "e2e"` by
 * dynamic import and passes it as `authInstance` to <Providers>.
 *
 * The access token is an obviously fake string; the mock API reads the role
 * from its suffix (see tests/mock-api/server.ts).
 */
import type { AccountInfo, IPublicClientApplication } from "@azure/msal-browser";

export const STUB_ROLES = ["Viewer"] as const;
export const STUB_TOKEN = `ns-e2e-fake-token.${STUB_ROLES[0]}`;

export const STUB_ACCOUNT: AccountInfo = {
  homeAccountId: "e2e-home-account",
  environment: "login.example.invalid",
  tenantId: "e2e-tenant",
  username: "e2e.user@example.invalid",
  localAccountId: "e2e-local-account",
  name: "E2E User",
  idTokenClaims: { roles: [...STUB_ROLES] },
};

export function createStubMsalInstance(): IPublicClientApplication {
  const logger = { info: () => undefined, verbose: () => undefined, clone: () => logger };
  const stub = {
    initializeWrapperLibrary: () => undefined,
    getLogger: () => logger,
    addEventCallback: () => "e2e-callback",
    removeEventCallback: () => undefined,
    initialize: () => Promise.resolve(),
    handleRedirectPromise: () => Promise.resolve(null),
    getAllAccounts: () => [STUB_ACCOUNT],
    getActiveAccount: () => STUB_ACCOUNT,
    setActiveAccount: () => undefined,
    loginRedirect: () => Promise.resolve(),
    acquireTokenSilent: () => Promise.resolve({ accessToken: STUB_TOKEN }),
    acquireTokenRedirect: () => Promise.resolve(),
    logoutRedirect: () => Promise.resolve(),
  };
  return stub as unknown as IPublicClientApplication;
}
