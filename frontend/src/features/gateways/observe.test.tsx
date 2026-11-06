import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { QueryProvider, createApiClient } from "../../api/index.js";
import { coverageText, freshnessText } from "./GatewayObserveSummary";
import { gatewayDetailHref, gatewayInventoryPath, gatewayPath, gatewaysPath } from "./paths";
import { gatewaysRoutes } from "./routes";
import type { GatewayDetail, GatewayInventory, GatewayRegistration } from "./types";

vi.mock("../../app/domain", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../app/domain")>();
  return {
    ...actual,
    useSelectedDomain: () => ({
      domainId: "commercial:contoso:catalog:domain:finance",
      domains: [],
      setDomain: () => undefined,
      status: "ready" as const,
    }),
  };
});

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});

afterEach(cleanup);

const DOMAIN = "commercial:contoso:catalog:domain:finance";
const GW = `gw-${"1".repeat(32)}`;
const NOW = "2026-10-20T10:00:00Z";

const registration: GatewayRegistration = {
  id: GW,
  domain_id: DOMAIN,
  cloud: "commercial",
  name: "apim-observe",
  tier: "premium_v2",
  mode: "observe",
  mode_changed_at: null,
  mode_changed_by: null,
  mode_revision: 0,
  preflight: null,
  diagnostics: { gateway_logs: true, gateway_llm_logs: false },
  last_sync_at: NOW,
  last_sync_status: "ok",
  freshness_seconds: 7200,
  coverage: 0.5,
};

const inventory: GatewayInventory = {
  gateway_id: GW,
  taken_at: NOW,
  apis: [{ id: "chat-api", name: "Chat", path: "openai", protocols: ["https"] }],
  operations: [],
  products: [],
  product_api_links: [],
  backends: [
    {
      id: "pool",
      type: "Pool",
      pool_members: [{ backend_id: "east", weight: 3, priority: 1 }],
      circuit_breaker_rules: [{ name: "trip", failure_count: 3, trip_duration: "PT30S" }],
    },
  ],
  policy_fragments: [{ name: "token-limit" }],
  subscriptions: [{ id: "sub-1", display_name: "Finance" }],
};

interface Reply {
  status: number;
  body: unknown;
}

function setup(entry: string, routes: Record<string, Reply>): void {
  const fetchImpl = vi.fn<typeof fetch>((input) => {
    const route = routes[new URL(String(input)).pathname];
    return Promise.resolve(
      route === undefined
        ? new Response(JSON.stringify({ status: 404 }), { status: 404 })
        : new Response(JSON.stringify(route.body), { status: route.status }),
    );
  });
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("t"),
    fetchImpl,
    maxRetries: 0,
  });
  const router = createMemoryRouter(gatewaysRoutes, { initialEntries: [entry] });
  render(
    <QueryProvider client={client}>
      <RouterProvider router={router} />
    </QueryProvider>,
  );
}

describe("observe helpers", () => {
  it("formats freshness and coverage, and says so when they are not reported", () => {
    expect(freshnessText(45)).toBe("45 s");
    expect(freshnessText(300)).toBe("5 min");
    expect(freshnessText(7200)).toBe("2 h");
    expect(freshnessText(null)).toBe("Not reported");
    expect(coverageText(0.85)).toBe("85%");
    expect(coverageText(undefined)).toBe("Not reported");
  });

  it("builds the detail href with the domain and gateway in the query", () => {
    expect(gatewayDetailHref(DOMAIN, GW)).toBe(
      `/gateways/detail?domain_id=${encodeURIComponent(DOMAIN)}&gateway_id=${GW}`,
    );
  });
});

describe("gateways list observe fields", () => {
  it("shows tier, diagnostics state, last sync, freshness, coverage and the detail link", async () => {
    setup("/gateways", {
      [gatewaysPath(DOMAIN)]: { status: 200, body: { items: [registration], next_cursor: null } },
    });
    expect(await screen.findByTestId("gateway-tier")).toHaveTextContent("premium_v2");
    const diag = screen.getByTestId("gateway-diagnostics");
    expect(within(diag).getByText(/GatewayLogs:/)).toHaveTextContent("enabled");
    expect(within(diag).getByText(/GatewayLlmLogs:/)).toHaveTextContent("not enabled");
    // A flag the server omitted is shown as not enabled, never as healthy.
    expect(within(diag).getByText(/GatewayMCPLogs:/)).toHaveTextContent("not enabled");
    expect(screen.getByTestId("gateway-last-sync")).toHaveTextContent("Synced");
    expect(screen.getByTestId("gateway-freshness")).toHaveTextContent("2 h");
    expect(screen.getByTestId("gateway-coverage")).toHaveTextContent("50%");
    expect(screen.getByTestId("gateway-detail-link")).toHaveAttribute(
      "href",
      gatewayDetailHref(DOMAIN, GW),
    );
  });
});

describe("gateway detail", () => {
  const entry = `/gateways/detail?gateway_id=${GW}`;

  it("renders the inventory tables with pool members and circuit breakers", async () => {
    const detail: GatewayDetail = { ...registration, inventory_counts: { apis: 1 } };
    setup(entry, {
      [gatewayPath(DOMAIN, GW)]: { status: 200, body: detail },
      [gatewayInventoryPath(DOMAIN, GW)]: { status: 200, body: inventory },
    });
    expect(await screen.findByTestId("inventory-apis")).toBeInTheDocument();
    expect(screen.getByTestId("inventory-apis-row")).toHaveTextContent("chat-api");
    expect(screen.getByTestId("pool-member")).toHaveTextContent("east (weight 3, priority 1)");
    expect(screen.getByTestId("circuit-breaker")).toHaveTextContent("trip 3 failures");
    expect(screen.getByTestId("inventory-fragments-row")).toHaveTextContent("token-limit");
    expect(screen.getByTestId("inventory-subscriptions-row")).toHaveTextContent("sub-1");
    // Empty sections say so instead of rendering an empty table.
    expect(screen.getAllByText("None in the latest snapshot.").length).toBeGreaterThan(0);
  });

  it("shows an empty state when no inventory has been synced", async () => {
    setup(entry, { [gatewayPath(DOMAIN, GW)]: { status: 200, body: registration } });
    expect(await screen.findByTestId("inventory-empty")).toBeInTheDocument();
  });

  it("shows not-found for an unknown gateway", async () => {
    setup(entry, {});
    await waitFor(() => {
      expect(screen.getByTestId("gateway-not-found")).toBeInTheDocument();
    });
  });

  it("asks for a gateway when none is chosen", async () => {
    setup("/gateways/detail", {});
    expect(await screen.findByTestId("gateway-required")).toBeInTheDocument();
  });
});
