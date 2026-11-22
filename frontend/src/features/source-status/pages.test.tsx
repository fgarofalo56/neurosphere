import "@testing-library/jest-dom/vitest";
import type { AccountInfo, IPublicClientApplication } from "@azure/msal-browser";
import { MsalProvider } from "@azure/msal-react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { createStubMsalInstance } from "../../../tests/e2e-support/stubMsal";
import { QueryProvider, createApiClient } from "../../api/index.js";
import type { DomainEntry } from "../../app/domain";
import { AdminTransportProvider } from "../admin/shared/transport";
import { RegisterGatewayPage } from "../admin/gateways/RegisterGatewayPage";
import { AuditPage } from "../audit/AuditPage";
import { CatalogExplorerPage } from "../catalog/CatalogExplorerPage";
import { StaleAgentsPage } from "../catalog/StaleAgentsPage";
import { DashboardPage } from "../dashboards/DashboardPage";
import { EvaluationsPage } from "../evaluations/EvaluationsPage";
import { ForecastPage } from "../finops/ForecastPage";
import { GatewaysPage } from "../gateways/GatewaysPage";
import { MapPage } from "../map/MapPage";
import { MapTablePage } from "../map-table/MapTablePage";
import { OverviewPage } from "../overview/OverviewPage";
import { QualityPage } from "../quality/QualityPage";
import { RecommendationListPage } from "../recommendations/RecommendationListPage";
import { ReconciliationPage } from "../reconciliation/ReconciliationPage";
import { ReplayPage } from "../replay/ReplayPage";
import { WorkspacePage } from "../workspaces/WorkspacePage";
import { WORKSPACES } from "../workspaces/personas";

// Each page is rendered through its own data hooks over one fake fetch that answers
// `GET /api/v1/sources/status`; the page-specific answer is an empty result.

const selected = vi.hoisted(() => ({ domainId: "dom-1" }));

vi.mock("../../app/domain", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../app/domain")>();
  const entry: DomainEntry = {
    domain_id: "dom-1",
    display_name: "Finance",
    display_name_source: "catalog",
    cloud: "commercial",
    permissions: ["data.read"],
  };
  return {
    ...actual,
    useSelectedDomain: () => ({
      domainId: selected.domainId,
      domains: [entry],
      setDomain: () => undefined,
      status: "ready" as const,
    }),
  };
});

// jsdom has no WebGL: the map renderer is a recorder.
vi.mock("../map/renderer", () => ({
  createMapRenderer: vi.fn(() => ({
    fit: vi.fn(),
    update: vi.fn(),
    setEdgeOffset: vi.fn(),
    select: vi.fn(),
    setReducedMotion: vi.fn(),
    kill: vi.fn(),
  })),
}));

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(() => {
  cleanup();
  selected.domainId = "dom-1";
});

const ALL_NOT_CONNECTED = {
  sources: [
    { source: "foundry", state: "not_connected", last_success_at: null, available: true },
    { source: "apim_gateway", state: "not_connected", last_success_at: null, available: true },
    { source: "billing", state: "not_connected", last_success_at: null, available: true },
    {
      source: "azure_monitor_telemetry",
      state: "not_connected",
      last_success_at: null,
      available: false,
    },
  ],
};

const ALL_CONNECTED = {
  sources: ALL_NOT_CONNECTED.sources.map((s) => ({
    ...s,
    state: "connected_no_data",
    last_success_at: "2026-11-21T10:00:00Z",
  })),
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": status >= 400 ? "application/problem+json" : "application/json" },
  });
}

function problem(status: number, code: string, reason: string): Response {
  return json(
    {
      schema_version: "1.0.0",
      type: "https://neurosphere.invalid/problems/x",
      title: "Problem",
      status,
      detail: reason,
      instance: "/x",
      code,
      reason,
      retryable: false,
      correlation_id: "corr-test-1",
    },
    status,
  );
}

const PAGE = { items: [], next_cursor: null };
const VIEWPORT = {
  domain_id: "dom-1",
  nodes: [],
  edges: [],
  truncated: false,
  truncation_reason: null,
  next_cursor: null,
  coverage: { state: "complete", lag_seconds: 0, as_of: null },
};
const FRESH = { watermark: null, lag_seconds: null, billing_source_freshness: null };
const UNKNOWN = { value: null, status: "unknown", complete: false, price_version: null };
const WINDOW = { start: "2026-11-01T00:00:00Z", end: "2026-11-21T00:00:00Z" };

/** The page's own data endpoints, each answering "nothing yet". */
function pageAnswer(url: URL): Response {
  const p = decodeURIComponent(url.pathname);
  if (p.includes("/dashboards/")) {
    return json({
      metric: "cost",
      domain_id: "dom-1",
      grain: "day",
      window: WINDOW,
      freshness: FRESH,
      analytics: { state: "available", reason: null },
      complete: true,
      truncated: false,
      series: [],
      price_versions: [],
    });
  }
  if (p.includes("/reconciliation")) {
    return json({
      domain_id: "dom-1",
      window: WINDOW,
      freshness: FRESH,
      complete: true,
      truncated: false,
      reference: { label: "ref", amount: UNKNOWN, currency: null },
      references: [],
      sources: [],
      unknown_remainder: { ...UNKNOWN, unit: "entries" },
      disclaimer: "not_all_spend_observable",
    });
  }
  if (p.includes("/forecast")) return problem(409, "conflict", "price_version_unresolved");
  if (p.includes("/quality")) {
    return json({
      trends: [],
      coverage: [],
      missing_labels: { judged: null, labelled: null, missing: null },
      pilot_grounded_rate: {
        value: null,
        lower: null,
        upper: null,
        level: null,
        n: 0,
        method: "not_estimable",
        target: 0.9,
        target_label: "target",
      },
      drift_alerts: [],
    });
  }
  if (p.includes("/viewport") || p.includes("/map")) return json(VIEWPORT);
  if (p.endsWith("/audit/domains")) {
    return json({
      items: [{ domain_id: "dom-1", display_name: "Finance", display_name_source: "catalog" }],
    });
  }
  if (p.includes("/audit/") && p.endsWith("/records")) {
    return problem(503, "dependency_transient", "audit_store_unconfigured");
  }
  if (p.includes("/stale")) {
    return json({
      plan_id: "plan-1",
      as_of: "2026-11-21T10:00:00Z",
      window_days: 30,
      candidates: [],
      truncated: false,
    });
  }
  return json(PAGE);
}

function msalFor(roles: readonly string[]): IPublicClientApplication {
  const acc: AccountInfo = {
    homeAccountId: "home",
    environment: "login.example.invalid",
    tenantId: "tenant",
    username: "someone@example.invalid",
    localAccountId: "local",
    name: "Test User",
    idTokenClaims: { roles: [...roles] },
  };
  const base = createStubMsalInstance() as unknown as Record<string, unknown>;
  return {
    ...base,
    getAllAccounts: () => [acc],
    getActiveAccount: () => acc,
  } as unknown as IPublicClientApplication;
}

interface Options {
  readonly roles: readonly string[];
  readonly status: Response | "fail";
  readonly path?: string;
}

function mount(ui: ReactElement, opts: Options) {
  const fetchImpl = vi.fn<typeof fetch>((input) => {
    const url = new URL(String(input));
    if (url.pathname === "/api/v1/sources/status") {
      return opts.status === "fail"
        ? Promise.resolve(json({ detail: "boom" }, 500))
        : Promise.resolve(opts.status.clone());
    }
    return Promise.resolve(pageAnswer(url));
  });
  const getToken = (): Promise<string> => Promise.resolve("t");
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken,
    fetchImpl,
    maxRetries: 0,
  });
  return render(
    <MsalProvider instance={msalFor(opts.roles)}>
      <QueryProvider client={client}>
        <AdminTransportProvider transport={{ baseUrl: "http://api.test", getToken, fetchImpl }}>
          <MemoryRouter initialEntries={[opts.path ?? "/?domain_id=dom-1"]}>{ui}</MemoryRouter>
        </AdminTransportProvider>
      </QueryProvider>
    </MsalProvider>,
  );
}

interface PageCase {
  readonly name: string;
  readonly ui: () => ReactElement;
  /** The empty state's own test id, where the page has one. */
  readonly href: string;
  readonly before?: () => Promise<void>;
  readonly domain?: string;
  readonly path?: string;
}

const CONNECTORS = "/admin/sources/connectors";

const CASES: readonly PageCase[] = [
  {
    name: "Overview",
    ui: () => <OverviewPage />,
    href: CONNECTORS,
    domain: "",
  },
  {
    name: "Workspace",
    ui: () => <WorkspacePage def={WORKSPACES[0] as (typeof WORKSPACES)[number]} />,
    href: CONNECTORS,
  },
  {
    name: "Dashboards",
    ui: () => <DashboardPage title="Cost" metrics={["cost"]} />,
    href: CONNECTORS,
  },
  { name: "Reconciliation", ui: () => <ReconciliationPage />, href: CONNECTORS },
  { name: "Forecast", ui: () => <ForecastPage />, href: CONNECTORS },
  { name: "Map", ui: () => <MapPage />, href: CONNECTORS },
  { name: "Map table", ui: () => <MapTablePage />, href: CONNECTORS },
  { name: "Replay", ui: () => <ReplayPage />, href: CONNECTORS },
  { name: "Catalog explorer", ui: () => <CatalogExplorerPage />, href: CONNECTORS },
  {
    name: "Stale agents",
    ui: () => <StaleAgentsPage />,
    href: CONNECTORS,
    before: async () => {
      await userEvent.click(await screen.findByTestId("dry-run"));
    },
  },
  { name: "Quality", ui: () => <QualityPage />, href: CONNECTORS },
  { name: "Evaluations", ui: () => <EvaluationsPage />, href: CONNECTORS },
  { name: "Recommendations", ui: () => <RecommendationListPage />, href: CONNECTORS },
  { name: "Gateways", ui: () => <GatewaysPage />, href: "/admin/gateways" },
  { name: "Audit", ui: () => <AuditPage />, href: "/admin/system", path: "/?audit_domain=dom-1" },
  { name: "Admin gateways", ui: () => <RegisterGatewayPage />, href: "/admin/domains" },
];

function mountCase(c: PageCase, opts: Options) {
  selected.domainId = c.domain ?? "dom-1";
  return mount(c.ui(), c.path === undefined ? opts : { ...opts, path: c.path });
}

describe("source-aware empty states", () => {
  it.each(CASES)("$name links an administrator to the page that connects a source", async (c) => {
    mountCase(c, { roles: ["Admin"], status: json(ALL_NOT_CONNECTED) });
    await c.before?.();
    const wraps = await screen.findAllByTestId("source-status-admin-link", undefined, {
      timeout: 4000,
    });
    expect(wraps[0]?.querySelector("a")?.getAttribute("href")).toBe(c.href);
  });

  it.each(CASES)("$name tells everyone else to ask an administrator", async (c) => {
    mountCase(c, { roles: ["Viewer"], status: json(ALL_NOT_CONNECTED) });
    await c.before?.();
    const asks = await screen.findAllByTestId("source-status-ask-admin", undefined, {
      timeout: 4000,
    });
    expect(asks[0]).toHaveTextContent("Ask an administrator to connect a source");
    expect(screen.queryByTestId("source-status-admin-link")).toBeNull();
  });

  it("falls back to the page text when the status cannot be read", async () => {
    mountCase(CASES[8] as PageCase, { roles: ["Admin"], status: "fail" });
    expect(await screen.findByTestId("empty-state")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByTestId("source-status-admin-link")).toBeNull());
  });

  it("says data has not arrived yet, with the last success time, when sources are connected", async () => {
    mountCase(CASES[8] as PageCase, { roles: ["Admin"], status: json(ALL_CONNECTED) });
    const detail = await screen.findByTestId("source-status-detail");
    expect(detail).toHaveTextContent("data has not arrived yet");
    expect(detail).toHaveTextContent("2026-11-21 10:00 UTC");
  });
});
