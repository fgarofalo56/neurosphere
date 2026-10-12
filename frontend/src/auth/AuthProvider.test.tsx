// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { AccountInfo, IPublicClientApplication } from "@azure/msal-browser";
import { AuthProvider } from "./AuthProvider";
import { getToken } from "./token";
import { useRoles } from "./useRoles";
import type { AuthConfig } from "./config";

const SECRET_TOKEN = "eyJ.secret-access-token.sig";
const config: AuthConfig = {
  cloud: "government",
  tenantId: "t1",
  clientId: "c1",
  apiScope: "api://ns/.default",
};

function makeInstance(accounts: AccountInfo[]) {
  const logger = { info: vi.fn(), verbose: vi.fn(), clone: () => logger };
  const mock = {
    initializeWrapperLibrary: vi.fn(),
    getLogger: () => logger,
    addEventCallback: vi.fn(() => "cb"),
    removeEventCallback: vi.fn(),
    initialize: vi.fn(() => Promise.resolve()),
    handleRedirectPromise: vi.fn(() => Promise.resolve(null)),
    getAllAccounts: vi.fn(() => accounts),
    getActiveAccount: vi.fn(() => accounts[0] ?? null),
    setActiveAccount: vi.fn(),
    loginRedirect: vi.fn(() => Promise.resolve()),
    acquireTokenSilent: vi.fn(() => Promise.resolve({ accessToken: SECRET_TOKEN })),
    acquireTokenRedirect: vi.fn(() => Promise.resolve()),
    logoutRedirect: vi.fn(() => Promise.resolve()),
  };
  return mock;
}

function asInstance(mock: ReturnType<typeof makeInstance>): IPublicClientApplication {
  return mock as unknown as IPublicClientApplication;
}

const account = {
  homeAccountId: "h",
  environment: "login.microsoftonline.us",
  tenantId: "t1",
  username: "u@example.test",
  localAccountId: "l",
  idTokenClaims: { roles: ["Analyst", "Auditor"] },
} as AccountInfo;

const consoleSpies = () =>
  (["log", "info", "warn", "error", "debug"] as const).map((m) => vi.spyOn(console, m));

function Roles() {
  const { label } = useRoles();
  return <p>roles: {label}</p>;
}

describe("AuthProvider", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(cleanup);

  it("triggers loginRedirect when unauthenticated and hides children", async () => {
    const mock = makeInstance([]);
    render(
      <AuthProvider config={config} instance={asInstance(mock)}>
        <p>secret content</p>
      </AuthProvider>,
    );
    await waitFor(() =>
      expect(mock.loginRedirect).toHaveBeenCalledWith({ scopes: [config.apiScope] }),
    );
    expect(screen.queryByText("secret content")).toBeNull();
  });

  it("renders children and displays roles when signed in, without redirecting", async () => {
    const mock = makeInstance([account]);
    render(
      <AuthProvider config={config} instance={asInstance(mock)}>
        <Roles />
      </AuthProvider>,
    );
    expect(await screen.findByText("roles: Analyst, Auditor")).toBeTruthy();
    expect(mock.loginRedirect).not.toHaveBeenCalled();
  });

  it("getToken returns the silent token and never logs it", async () => {
    const spies = consoleSpies();
    const mock = makeInstance([account]);
    render(
      <AuthProvider config={config} instance={asInstance(mock)}>
        <p>in</p>
      </AuthProvider>,
    );
    await screen.findByText("in");
    await expect(getToken()).resolves.toBe(SECRET_TOKEN);
    expect(mock.acquireTokenSilent).toHaveBeenCalledWith({ scopes: [config.apiScope], account });
    for (const spy of spies) {
      expect(JSON.stringify(spy.mock.calls)).not.toContain(SECRET_TOKEN);
    }
  });
});
