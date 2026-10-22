import {
  PublicClientApplication,
  type Configuration,
  type IPublicClientApplication,
} from "@azure/msal-browser";
import { resolveAuthority } from "./authority";
import type { AuthConfig } from "./config";

export function buildMsalConfiguration(config: AuthConfig): Configuration {
  const { authority, knownAuthorities } = resolveAuthority(config.cloud, config.tenantId);
  const redirectUri =
    config.redirectUri ?? (typeof window === "undefined" ? undefined : window.location.origin);
  return {
    auth: {
      clientId: config.clientId,
      authority,
      knownAuthorities: [...knownAuthorities],
      ...(redirectUri === undefined ? {} : { redirectUri }),
    },
    // C8: sessionStorage only; no localStorage, no tokens in logs.
    // C8 governs tokens and auth state. PRP-28 separately stores ONE non-secret value in
    // localStorage: the last selected domain id, under `ns.lastDomain.<pseudonymous user key>`
    // (app/domain.tsx), cleared on sign-out. No token or other data is ever written there.
    cache: { cacheLocation: "sessionStorage" },
    system: {
      loggerOptions: {
        piiLoggingEnabled: false,
        // Swallow MSAL log output entirely so tokens can never reach console.
        loggerCallback: () => undefined,
      },
    },
  };
}

/** Creates the MSAL instance. Redirect flow is the default; no popup is used anywhere. */
export function createMsalInstance(config: AuthConfig): IPublicClientApplication {
  return new PublicClientApplication(buildMsalConfiguration(config));
}
