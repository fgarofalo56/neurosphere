import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import type { IPublicClientApplication } from "@azure/msal-browser";
import { App, type AppProps } from "./App";
import { appRoutes } from "./appRoutes";
import { useAppNavItems } from "./workspaceNav";

async function loadAuthInstance(): Promise<IPublicClientApplication | undefined> {
  // e2e builds only: a fake MSAL instance so tests need no tenant. Production
  // modes never take this branch, so the stub is tree-shaken out of the bundle.
  if (import.meta.env.MODE === "e2e") {
    const { createStubMsalInstance } = await import("../../tests/e2e-support/stubMsal");
    return createStubMsalInstance();
  }
  if (import.meta.env.MODE === "demo") {
    // Local demo only (`pnpm demo`): same stub sign-in as e2e, as the Steward persona so the
    // demo shows write-capable pages. Dead code in production builds.
    const { createStubMsalInstance } = await import("../../tests/e2e-support/stubMsal");
    return createStubMsalInstance(["Steward"]);
  }
  return undefined;
}

async function renderApp(authInstance: IPublicClientApplication | undefined): Promise<ReactNode> {
  const props: AppProps = { extraRoutes: appRoutes, useNavItems: useAppNavItems, authInstance };
  if (import.meta.env.MODE === "demo") {
    const demo = await import("./demo");
    return demo.withDemoBanner(<App {...props} configLoader={demo.demoConfigLoader} />);
  }
  return <App {...props} />;
}

const container = document.getElementById("root");
if (container === null) throw new Error("Missing #root element");
const root = createRoot(container);

void loadAuthInstance()
  .then(renderApp)
  .then((tree) => {
    root.render(<StrictMode>{tree}</StrictMode>);
  });
