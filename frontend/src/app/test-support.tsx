import type { AccountInfo, IPublicClientApplication } from "@azure/msal-browser";
import { MsalProvider } from "@azure/msal-react";
import { render } from "@testing-library/react";
import { vi } from "vitest";
import { createMemoryRouter, RouterProvider, useLocation } from "react-router";
import { QueryProvider, createApiClient } from "../api/index.js";
import { createStubMsalInstance } from "../../tests/e2e-support/stubMsal";
import { DomainProvider, type DomainEntry } from "./domain";
import { createAppRoutes, type AppRoutesOptions } from "./routes";

/** Shared setup for the shell and domain tests (not a test file). */

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

/** Fluent components (MessageBar, Dropdown) need ResizeObserver, which jsdom lacks. */
export function stubResizeObserver(): void {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
}

export function domainEntry(
  id: string,
  name: string,
  source: "catalog" | "derived" = "catalog",
  permissions: readonly string[] = ["data.read"],
): DomainEntry {
  return {
    domain_id: id,
    display_name: name,
    display_name_source: source,
    cloud: "commercial",
    permissions,
  };
}

export function problemResponse(status: number): Response {
  return new Response(JSON.stringify({ status, code: "forbidden" }), {
    status,
    headers: { "content-type": "application/problem+json" },
  });
}

export function accountWith(homeAccountId: string, roles: readonly string[]): AccountInfo {
  return {
    homeAccountId,
    environment: "login.example.invalid",
    tenantId: "test-tenant",
    username: "someone@example.invalid",
    localAccountId: "local",
    name: "Test User",
    idTokenClaims: { roles: [...roles] },
  };
}

function msalFor(account: AccountInfo): IPublicClientApplication {
  const base = createStubMsalInstance() as unknown as Record<string, unknown>;
  return {
    ...base,
    getAllAccounts: () => [account],
    getActiveAccount: () => account,
    logoutRedirect: vi.fn(() => Promise.resolve()),
  } as unknown as IPublicClientApplication;
}

/** Prints the current location so tests can assert the URL. */
export function LocationProbe() {
  const location = useLocation();
  return <p data-testid="location">{`${location.pathname}${location.search}`}</p>;
}

export interface ShellHarness {
  readonly account: AccountInfo;
  /** Answers `GET /api/v1/me/domains`; default lists nothing. */
  readonly respond: () => Response;
  readonly path?: string;
  readonly routes?: AppRoutesOptions;
}

/** Renders the full shell with MSAL stub, query client, domain provider and a memory router. */
export function renderShell(h: ShellHarness) {
  const fetchImpl = vi.fn<typeof fetch>(() => Promise.resolve(h.respond()));
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("test-credential"),
    fetchImpl,
    maxRetries: 0,
  });
  const msal = msalFor(h.account);
  const router = createMemoryRouter(
    createAppRoutes({
      extraRoutes: [{ path: "page", element: <LocationProbe /> }],
      navItems: [
        { to: "/", label: "Home", group: "Overview" },
        { to: "/page", label: "Some page", group: "Quality" },
      ],
      ...h.routes,
    }),
    { initialEntries: [h.path ?? "/page"] },
  );
  const view = render(
    <MsalProvider instance={msal}>
      <QueryProvider client={client}>
        <DomainProvider>
          <RouterProvider router={router} />
        </DomainProvider>
      </QueryProvider>
    </MsalProvider>,
  );
  return { ...view, router, fetchImpl, msal };
}
