import type { AccountInfo, IPublicClientApplication } from "@azure/msal-browser";
import { MsalProvider } from "@azure/msal-react";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { QueryProvider, createApiClient } from "../../api/index.js";
import { NS_ROLES, type NsRole } from "../../auth/roles";
import { createStubMsalInstance } from "../../../tests/e2e-support/stubMsal";
import {
  MAX_OVERVIEW_CALLS,
  ROLE_TILES,
  TILE_CALLS,
  TILE_ORDER,
  countText,
  tileHref,
  tilesForRoles,
} from "./data";
import { OverviewPage } from "./OverviewPage";
import { STRINGS } from "./strings";

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(cleanup);

const API = "http://api.test";
const DOMAIN = "commercial:test:catalog:domain:finance";

function account(roles: readonly string[]): AccountInfo {
  return {
    homeAccountId: "home-overview",
    environment: "login.example.invalid",
    tenantId: "test-tenant",
    username: "someone@example.invalid",
    localAccountId: "local",
    name: "Test User",
    idTokenClaims: { roles: [...roles] },
  };
}

function msalFor(acc: AccountInfo): IPublicClientApplication {
  const base = createStubMsalInstance() as unknown as Record<string, unknown>;
  return {
    ...base,
    getAllAccounts: () => [acc],
    getActiveAccount: () => acc,
  } as unknown as IPublicClientApplication;
}

function renderOverview(roles: readonly string[], search = `?domain_id=${DOMAIN}`) {
  const client = createApiClient({
    baseUrl: API,
    getToken: () => Promise.resolve("test-credential"),
    fetchImpl: (input, init) => activeFetch(input, init),
    maxRetries: 0,
  });
  return render(
    <MsalProvider instance={msalFor(account(roles))}>
      <QueryProvider client={client}>
        <MemoryRouter initialEntries={[`/${search}`]}>
          <OverviewPage />
        </MemoryRouter>
      </QueryProvider>
    </MsalProvider>,
  );
}

const value = (v: number | null, complete = true) => ({
  value: v,
  status: v === null ? "unknown" : "known",
  complete: v === null ? false : complete,
  price_version: null,
});

function costSeries(key: string, currency: string, kind: string, total: unknown) {
  return { key, label: key, kind, unit: "currency", currency, total, points: [] };
}

const COST_BODY = {
  series: [
    costSeries("estimated:USD", "USD", "estimated", value(12.5, false)),
    costSeries("invoiced:USD", "USD", "invoiced", value(9.25)),
    costSeries("estimated:EUR", "EUR", "estimated", value(100)),
    costSeries("estimated:CAD", "CAD", "estimated", value(null)),
  ],
};

interface Calls {
  readonly urls: URL[];
}

type Handler = (url: URL) => Response;

let activeFetch: typeof fetch = () => Promise.reject(new Error("useApi() was not called"));

function json(body: unknown, status = 200, type = "application/json"): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": type } });
}

/**
 * Strict fake API for every tile source: an unmatched request rejects (the equivalent of MSW's
 * `onUnhandledRequest: "error"`; the shared MSW setup in tests/setup.ts does not enforce it under
 * msw 3). `over` replaces individual tile handlers.
 */
function useApi(over: Partial<Record<string, Handler>> = {}): Calls {
  const calls: Calls = { urls: [] };
  const d = encodeURIComponent(DOMAIN);
  const table: Record<string, { path: string; body: unknown }> = {
    cost: { path: `/api/v1/dashboards/domains/${d}/cost`, body: COST_BODY },
    review: {
      path: `/api/v1/review/domains/${d}/items`,
      body: { items: [{ id: "r1" }, { id: "r2" }], next_cursor: "c1" },
    },
    awaiting: {
      path: `/api/v1/actions/domains/${d}/intents`,
      body: { items: [], next_cursor: null },
    },
    map: {
      path: `/api/v1/map/domains/${d}/viewport`,
      body: {
        nodes: [],
        coverage: { state: "partial", lag_seconds: 30, as_of: "2026-10-04T00:00:00Z" },
      },
    },
    reports: {
      path: `/api/v1/reports/domains/${d}/reports`,
      body: { items: [{ id: "rp1", title: "Weekly spend" }], next_cursor: null },
    },
  };
  activeFetch = (input) => {
    const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw);
    calls.urls.push(url);
    for (const [name, route] of Object.entries(table)) {
      if (url.pathname === route.path) {
        return Promise.resolve(over[name]?.(url) ?? json(route.body));
      }
    }
    return Promise.reject(new Error(`unhandled request: ${url.pathname}`));
  };
  return calls;
}

function tile(id: string): HTMLElement {
  return screen.getByTestId(`tile-${id}`);
}

describe("role to tile mapping", () => {
  it("is explicit per role", () => {
    expect(ROLE_TILES).toEqual({
      Viewer: ["cost", "map", "reports"],
      Analyst: ["cost", "awaiting", "map", "reports"],
      Auditor: ["cost", "review", "map", "reports"],
      Steward: ["cost", "review", "awaiting", "map", "reports"],
      Admin: ["cost", "review", "awaiting", "map", "reports"],
    });
    expect(Object.keys(ROLE_TILES).sort()).toEqual([...NS_ROLES].sort());
  });

  it("unions roles, keeps display order and defaults to the Viewer set", () => {
    expect(tilesForRoles([])).toEqual(ROLE_TILES.Viewer);
    expect(tilesForRoles(["Auditor", "Analyst"] satisfies NsRole[])).toEqual([
      "cost",
      "review",
      "awaiting",
      "map",
      "reports",
    ]);
  });

  it("keeps the worst-case call count within the page ceiling", () => {
    const total = TILE_ORDER.reduce((n, id) => n + TILE_CALLS[id], 0);
    expect(total).toBeLessThanOrEqual(MAX_OVERVIEW_CALLS);
  });
});

describe("pure helpers", () => {
  it("shows N+ only when a next page exists", () => {
    expect(countText({ items: [1, 2], next_cursor: "x" })).toBe("2+");
    expect(countText({ items: [1, 2], next_cursor: null })).toBe("2");
    expect(countText({ items: [] })).toBe("0");
  });

  it("links carry domain_id", () => {
    expect(tileHref("review", "a:b")).toBe("/review?domain_id=a%3Ab");
  });
});

describe("OverviewPage", () => {
  it("renders every tile for a Steward with at most 7 calls and domain-scoped params", async () => {
    const calls = useApi();
    renderOverview(["Steward"]);
    await screen.findByTestId("review-count");
    await waitFor(() => expect(screen.getAllByTestId("cost-row")).toHaveLength(4));
    await screen.findByTestId("reports-count");
    await screen.findByTestId("map-coverage");
    await waitFor(() => expect(calls.urls).toHaveLength(6));
    expect(calls.urls.length).toBeLessThanOrEqual(MAX_OVERVIEW_CALLS);
    for (const url of calls.urls) {
      expect(url.searchParams.has("domain_id")).toBe(false);
      expect(url.searchParams.has("customer_id")).toBe(false);
    }
    const query = (suffix: string) =>
      calls.urls.filter((u) => u.pathname.endsWith(suffix)).map((u) => u.searchParams.toString());
    expect(query("/cost")).toEqual(["days=1"]);
    expect(query("/items")).toEqual(["state=pending"]);
    expect(query("/viewport")).toEqual(["node_budget=1"]);
    expect(query("/intents").sort()).toEqual([
      "state=awaiting_approval",
      "state=awaiting_confirmation",
    ]);
  });

  it("shows cost per currency without summing, with estimated and incomplete badges", async () => {
    useApi();
    renderOverview(["Viewer"]);
    const rows = await screen.findAllByTestId("cost-row");
    const text = rows.map((r) => r.textContent ?? "");
    expect(text[0]).toContain("USD");
    expect(text[0]).toContain("12.5");
    expect(text[0]).toContain("estimated");
    expect(within(rows[0] as HTMLElement).getByTestId("incomplete-marker")).toBeInTheDocument();
    expect(text[1]).toContain("9.25");
    expect(text[1]).toContain("invoiced");
    expect(text[2]).toContain("EUR");
    expect(text[2]).toContain("100");
    // Unknown stays "unknown", never 0, and nothing adds the series (21.75, 121.75 ...).
    expect(text[3]).toContain("CAD");
    expect(text[3]).toContain("unknown");
    expect(text[3]).not.toMatch(/\b0\b/);
    expect(tile("cost").textContent).not.toMatch(/21\.75|121\.75|131\.0/);
    expect(tile("cost")).toHaveTextContent(STRINGS.cost.window);
  });

  it("shows N+ on a paged list and the exact page size otherwise", async () => {
    useApi();
    renderOverview(["Steward"]);
    expect(await screen.findByTestId("review-count")).toHaveTextContent("2+");
    expect(await screen.findByTestId("reports-count")).toHaveTextContent("1");
    expect(screen.getByTestId("reports-count")).not.toHaveTextContent("+");
    expect(await screen.findByTestId("awaiting-awaiting_approval")).toHaveTextContent(": 0");
  });

  it("shows not loaded (never 0) and leaves other tiles rendered when one tile errors or is forbidden", async () => {
    useApi({
      review: () => json({ status: 500, code: "internal" }, 500, "application/problem+json"),
      cost: () => json({ status: 403, code: "forbidden" }, 403, "application/problem+json"),
    });
    renderOverview(["Steward"]);
    await screen.findByTestId("reports-count");
    await waitFor(() => expect(within(tile("review")).getByRole("alert")).toBeInTheDocument());
    await waitFor(() => expect(within(tile("cost")).getByRole("alert")).toBeInTheDocument());
    expect(tile("review")).toHaveTextContent(STRINGS.notLoaded);
    expect(tile("review")).toHaveTextContent(STRINGS.failed);
    expect(screen.queryByTestId("review-count")).toBeNull();
    expect(tile("cost")).toHaveTextContent(STRINGS.forbidden);
    expect(screen.queryAllByTestId("cost-row")).toHaveLength(0);
    expect(screen.getByTestId("reports-count")).toHaveTextContent("1");
    expect(screen.getByTestId("map-coverage")).toHaveTextContent("partial");
  });

  it("marks only the failing awaiting state as not loaded", async () => {
    useApi({
      awaiting: (url) =>
        url.searchParams.get("state") === "awaiting_approval"
          ? json({ status: 500, code: "internal" }, 500, "application/problem+json")
          : json({ items: [{}], next_cursor: "n" }),
    });
    renderOverview(["Analyst"]);
    expect(await screen.findByTestId("awaiting-awaiting_confirmation")).toHaveTextContent(": 1+");
    await waitFor(() =>
      expect(screen.getByTestId("awaiting-awaiting_approval")).toHaveTextContent(STRINGS.notLoaded),
    );
  });

  it("shows only the tiles for the caller's roles", async () => {
    const calls = useApi();
    renderOverview(["Viewer"]);
    await screen.findByTestId("reports-count");
    expect(screen.queryByTestId("tile-review")).toBeNull();
    expect(screen.queryByTestId("tile-awaiting")).toBeNull();
    for (const id of ["cost", "map", "reports"]) expect(tile(id)).toBeInTheDocument();
    expect(calls.urls.some((u) => u.pathname.includes("/review/"))).toBe(false);
    expect(calls.urls.some((u) => u.pathname.includes("/actions/"))).toBe(false);
  });

  it("links every tile into its feature with domain_id", async () => {
    useApi();
    renderOverview(["Admin"]);
    await screen.findByTestId("reports-count");
    const d = `domain_id=${encodeURIComponent(DOMAIN)}`;
    const hrefs = Object.fromEntries(
      TILE_ORDER.map((id) => [id, within(tile(id)).getByRole("link").getAttribute("href")]),
    );
    expect(hrefs).toEqual({
      cost: `/dashboards/cost?${d}`,
      review: `/review?${d}`,
      awaiting: `/actions?${d}`,
      map: `/map?${d}`,
      reports: `/reports?${d}`,
    });
  });

  it("prompts to pick a domain and makes no calls when there is none", async () => {
    const calls = useApi();
    renderOverview(["Admin"], "");
    expect(await screen.findByText(STRINGS.pickDomain)).toBeInTheDocument();
    expect(screen.queryByTestId("tile-cost")).toBeNull();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(calls.urls).toHaveLength(0);
  });
});
