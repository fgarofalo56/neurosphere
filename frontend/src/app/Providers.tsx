import { useLayoutEffect, useMemo, type ReactElement, type ReactNode } from "react";
import type { IPublicClientApplication } from "@azure/msal-browser";
import { createApiClient, QueryProvider } from "../api";
import { AuthProvider, getToken } from "../auth";
import { AppThemeProvider, useThemeStore } from "../design-system";
import { useAppConfig } from "./ConfigContext";
import { DomainProvider } from "./domain";

export interface ProvidersProps {
  readonly children: ReactNode;
  /** Test seam: inject a mocked MSAL instance (used by the e2e build only). */
  readonly authInstance?: IPublicClientApplication | undefined;
}

/**
 * Applies the deployment default theme (pack, mode, UI style) from runtime config before the
 * first paint, so screens that render before the shell (the sign-in redirect) are themed too. A
 * saved user choice still wins inside the store.
 */
function useDeploymentThemeDefault(): void {
  const config = useAppConfig();
  const applyDeploymentDefault = useThemeStore((s) => s.applyDeploymentDefault);
  const { defaultThemePack, defaultThemeMode, defaultUiStyle } = config;
  useLayoutEffect(() => {
    applyDeploymentDefault({
      ...(defaultThemePack === undefined ? {} : { packId: defaultThemePack }),
      ...(defaultThemeMode === undefined ? {} : { themeName: defaultThemeMode }),
      ...(defaultUiStyle === undefined ? {} : { styleId: defaultUiStyle }),
    });
  }, [applyDeploymentDefault, defaultThemePack, defaultThemeMode, defaultUiStyle]);
}

/**
 * SINGLE PLACE for provider composition, outermost first. The theme provider
 * wraps the auth provider so the login redirect screen is themed.
 */
export function Providers({ children, authInstance }: ProvidersProps): ReactElement {
  const config = useAppConfig();
  useDeploymentThemeDefault();
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
