import { useEffect, useMemo, type ReactNode } from "react";
import { InteractionStatus, type IPublicClientApplication } from "@azure/msal-browser";
import { MsalProvider, useIsAuthenticated, useMsal } from "@azure/msal-react";
import type { AuthConfig } from "./config";
import { createMsalInstance } from "./msal";
import { registerTokenSource } from "./token";

export interface AuthProviderProps {
  readonly config: AuthConfig;
  readonly children: ReactNode;
  /** Test seam: inject a mocked MSAL instance. Production omits it. */
  readonly instance?: IPublicClientApplication | undefined;
  /** Shown while sign-in is in progress. */
  readonly fallback?: ReactNode;
}

/**
 * UX gate only: an unauthenticated visitor is redirected to sign-in. This is
 * NOT security; the API validates every token and enforces authorization.
 */
function AuthGate({
  apiScope,
  fallback,
  children,
}: {
  apiScope: string;
  fallback: ReactNode;
  children: ReactNode;
}) {
  const { instance, inProgress } = useMsal();
  const authenticated = useIsAuthenticated();

  useEffect(() => {
    const [first] = instance.getAllAccounts();
    if (first !== undefined && instance.getActiveAccount() === null) {
      instance.setActiveAccount(first);
    }
  }, [instance, authenticated]);

  useEffect(() => {
    if (!authenticated && inProgress === InteractionStatus.None) {
      void instance.loginRedirect({ scopes: [apiScope] });
    }
  }, [authenticated, inProgress, instance, apiScope]);

  return <>{authenticated ? children : fallback}</>;
}

export function AuthProvider({ config, children, instance, fallback = null }: AuthProviderProps) {
  const msal = useMemo(() => instance ?? createMsalInstance(config), [instance, config]);

  useEffect(() => registerTokenSource(msal, config.apiScope), [msal, config.apiScope]);

  return (
    <MsalProvider instance={msal}>
      <AuthGate apiScope={config.apiScope} fallback={fallback}>
        {children}
      </AuthGate>
    </MsalProvider>
  );
}
