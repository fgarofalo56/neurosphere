/**
 * Local demo mode (`pnpm demo`, Vite --mode demo). Loaded only by a dynamic import behind
 * `import.meta.env.MODE === "demo"` in main.tsx, so it is dead code in production builds.
 */
import { Suspense, lazy, type ReactElement, type ReactNode } from "react";
import type { AppConfig } from "../config";
import { DemoBanner } from "./DemoBanner";

const DEFAULT_API_PORT = "5181";

/** Runtime config pointing at the local mock API; no tenant, no Azure. */
export function demoConfig(env: Record<string, unknown> = import.meta.env): AppConfig {
  const raw = env["VITE_NS_DEMO_API_PORT"];
  const port = typeof raw === "string" && /^\d{2,5}$/.test(raw) ? raw : DEFAULT_API_PORT;
  return {
    cloud: "commercial",
    tenantId: "00000000-0000-0000-0000-000000000000",
    clientId: "00000000-0000-0000-0000-000000000000",
    apiBaseUrl: `http://127.0.0.1:${port}`,
    apiScope: "api://neurosphere-demo/access_as_user",
  };
}

export const demoConfigLoader = (): Promise<AppConfig> => Promise.resolve(demoConfig());

// Static mockup gallery (PRP-30 item 4): rendered instead of the app under /__mockups/...
// Lazy so the gallery loads only when asked for, and only ever through this demo-only module.
const MockupGallery = lazy(() => import("./mockups"));
const MOCKUP_PATH_PREFIX = "/__mockups/";

export function withDemoBanner(app: ReactNode): ReactElement {
  const pathname = window.location.pathname;
  if (pathname.startsWith(MOCKUP_PATH_PREFIX)) {
    return (
      <Suspense fallback={null}>
        <MockupGallery pathname={pathname} />
      </Suspense>
    );
  }
  return (
    <>
      <DemoBanner />
      {app}
    </>
  );
}
