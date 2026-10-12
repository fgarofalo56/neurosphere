import { useEffect, useMemo, useState, type ReactElement } from "react";
import type { IPublicClientApplication } from "@azure/msal-browser";
import { createBrowserRouter, type RouteObject } from "react-router";
import { RouterProvider } from "react-router/dom";
import { loadConfig, type AppConfig } from "./config";
import { ConfigContext } from "./ConfigContext";
import { ConfigErrorScreen } from "./ConfigErrorScreen";
import { ErrorBoundary } from "./ErrorBoundary";
import { Providers } from "./Providers";
import { createAppRoutes, type NavItem } from "./routes";

export interface AppProps {
  readonly extraRoutes?: readonly RouteObject[];
  readonly navItems?: readonly NavItem[];
  readonly useNavItems?: () => readonly NavItem[];
  /** Test seam (e2e build only): mocked MSAL instance. */
  readonly authInstance?: IPublicClientApplication | undefined;
  /** Injectable for tests; defaults to fetching /config.json. */
  readonly configLoader?: () => Promise<AppConfig>;
}

type ConfigState =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly config: AppConfig }
  | { readonly status: "error"; readonly error: unknown };

// Stable reference so the startup effect does not re-run on every render.
const defaultConfigLoader = (): Promise<AppConfig> => loadConfig();

export function App({
  extraRoutes,
  navItems,
  useNavItems,
  authInstance,
  configLoader = defaultConfigLoader,
}: AppProps): ReactElement {
  const [state, setState] = useState<ConfigState>({ status: "loading" });

  // Config is loaded once at startup.
  useEffect(() => {
    let cancelled = false;
    configLoader().then(
      (config) => {
        if (!cancelled) setState({ status: "ready", config });
      },
      (error: unknown) => {
        if (!cancelled) setState({ status: "error", error });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [configLoader]);

  const router = useMemo(
    () => createBrowserRouter(createAppRoutes({ extraRoutes, navItems, useNavItems })),
    [extraRoutes, navItems, useNavItems],
  );

  if (state.status === "loading") return <p role="status">Loading configuration...</p>;
  if (state.status === "error") return <ConfigErrorScreen error={state.error} />;
  return (
    <ConfigContext.Provider value={state.config}>
      <Providers authInstance={authInstance}>
        <ErrorBoundary>
          <RouterProvider router={router} />
        </ErrorBoundary>
      </Providers>
    </ConfigContext.Provider>
  );
}
