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

function accountFor(roles: readonly string[]): AccountInfo {
  return {
    homeAccountId: "e2e-home-account",
    environment: "login.example.invalid",
    tenantId: "e2e-tenant",
    username: "e2e.user@example.invalid",
    localAccountId: "e2e-local-account",
    name: "E2E User",
    idTokenClaims: { roles: [...roles] },
  };
}

export const STUB_ACCOUNT: AccountInfo = accountFor(STUB_ROLES);

/** The persona is the first role; the mock API reads it from the token suffix. */
export function createStubMsalInstance(
  roles: readonly string[] = STUB_ROLES,
): IPublicClientApplication {
  const account = accountFor(roles);
  const token = `ns-e2e-fake-token.${roles[0] ?? STUB_ROLES[0]}`;
  const logger = { info: () => undefined, verbose: () => undefined, clone: () => logger };
  const stub = {
    initializeWrapperLibrary: () => undefined,
    getLogger: () => logger,
    addEventCallback: () => "e2e-callback",
    removeEventCallback: () => undefined,
    initialize: () => Promise.resolve(),
    handleRedirectPromise: () => Promise.resolve(null),
    getAllAccounts: () => [account],
    getActiveAccount: () => account,
    setActiveAccount: () => undefined,
    loginRedirect: () => Promise.resolve(),
    acquireTokenSilent: () => Promise.resolve({ accessToken: token }),
    acquireTokenRedirect: () => Promise.resolve(),
    logoutRedirect: () => Promise.resolve(),
  };
  return stub as unknown as IPublicClientApplication;
}
