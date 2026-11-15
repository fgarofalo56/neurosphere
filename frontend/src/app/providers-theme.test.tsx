import type { IPublicClientApplication } from "@azure/msal-browser";
import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createStubMsalInstance } from "../../tests/e2e-support/stubMsal";
import { THEME_STORAGE_KEY, reloadStoredTheme } from "../design-system";
import { ConfigContext } from "./ConfigContext";
import { Providers } from "./Providers";
import type { AppConfig } from "./config";

/**
 * #125: the deployment default theme must reach screens that render before the shell, such as
 * the sign-in redirect screen. Providers is rendered here WITHOUT Shell and with no signed-in
 * account, so only the auth fallback is on screen.
 */

const CONFIG: AppConfig = {
  cloud: "commercial",
  tenantId: "t",
  clientId: "c",
  apiBaseUrl: "http://api.test",
  apiScope: "api://test/access",
  defaultThemePack: "sample-agency",
  defaultThemeMode: "dark",
};

/** MSAL with no account: the AuthGate shows its fallback and calls loginRedirect. */
function signedOut(): IPublicClientApplication {
  const base = createStubMsalInstance() as unknown as Record<string, unknown>;
  return {
    ...base,
    getAllAccounts: () => [],
    getActiveAccount: () => null,
  } as unknown as IPublicClientApplication;
}

function renderRedirectScreen(config: AppConfig): HTMLElement {
  const { container } = render(
    <ConfigContext.Provider value={config}>
      <Providers authInstance={signedOut()}>
        <p>app</p>
      </Providers>
    </ConfigContext.Provider>,
  );
  const root = container.querySelector<HTMLElement>("[data-theme]");
  if (root === null) throw new Error("theme root not rendered");
  return root;
}

beforeEach(() => {
  window.localStorage.clear();
  reloadStoredTheme();
});
afterEach(() => {
  cleanup();
  window.localStorage.clear();
  reloadStoredTheme();
});

describe("deployment default theme before the shell", () => {
  it("applies the configured pack and mode to the sign-in redirect screen", () => {
    const root = renderRedirectScreen(CONFIG);
    expect(root.dataset["theme"]).toBe("dark");
    expect(root.dataset["themePack"]).toBe("sample-agency");
    expect(root.textContent).not.toContain("app");
  });

  it("keeps a saved user choice over the deployment default", () => {
    window.localStorage.setItem(
      THEME_STORAGE_KEY,
      JSON.stringify({ packId: "default", themeName: "light" }),
    );
    reloadStoredTheme();
    const root = renderRedirectScreen(CONFIG);
    expect(root.dataset["theme"]).toBe("light");
    expect(root.dataset["themePack"]).toBe("default");
  });
});
