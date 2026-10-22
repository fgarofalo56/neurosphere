import { useMemo, type ReactElement, type ReactNode } from "react";
import type { IPublicClientApplication } from "@azure/msal-browser";
import { createApiClient, QueryProvider } from "../api";
import { AuthProvider, getToken } from "../auth";
import { AppThemeProvider } from "../design-system";
import { useAppConfig } from "./ConfigContext";
import { DomainProvider } from "./domain";

export interface ProvidersProps {
  readonly children: ReactNode;
  /** Test seam: inject a mocked MSAL instance (used by the e2e build only). */
  readonly authInstance?: IPublicClientApplication | undefined;
}

/**
 * SINGLE PLACE for provider composition, outermost first. The theme provider
 * wraps the auth provider so the login redirect screen is themed.
 */
export function Providers({ children, authInstance }: ProvidersProps): ReactElement {
  const config = useAppConfig();
  const client = useMemo(
    () => createApiClient({ baseUrl: config.apiBaseUrl, getToken }),
    [config.apiBaseUrl],
  );
  return (
    <AppThemeProvider>
      <AuthProvider config={config} instance={authInstance}>
        <QueryProvider client={client}>
          <DomainProvider>{children}</DomainProvider>
        </QueryProvider>
      </AuthProvider>
    </AppThemeProvider>
  );
}
