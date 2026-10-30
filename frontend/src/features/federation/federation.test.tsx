import type { AccountInfo, IPublicClientApplication } from "@azure/msal-browser";
import { MsalProvider } from "@azure/msal-react";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import { QueryProvider, createApiClient } from "../../api/index.js";
import { createStubMsalInstance } from "../../../tests/e2e-support/stubMsal";
import { groupByCurrency, type MergedSummary } from "./data";
import { FederationPage, totalText } from "./FederationPage";

afterEach(cleanup);

const API = "http://api.test";

const SUMMARY: MergedSummary = {
  cloud: "commercial",
  boundary_id: "boundary-test",
  window_start: "2026-09-15T00:00:00Z",
  window_end: "2026-10-15T00:00:00Z",
  cells: [
    { cell_id: "cell-a", state: "ok" },
    { cell_id: "cell-b", state: "denied" },
    { cell_id: "cell-c", state: "unavailable" },
  ],
  domains: [
    {
      domain_id: "d-one",
      request_count: 10,
      error_count: null,
      unknown_outcome_count: null,
      costs: [{ kind: "estimated", currency: "USD", amount: "5.00", complete: true }],
      complete: true,
    },
  ],
  totals: [
    { kind: "estimated", currency: "USD", amount: "100.00", complete: true },
    { kind: "invoiced", currency: "USD", amount: null, complete: false },
    { kind: "estimated", currency: "EUR", amount: "40.00", complete: false },
  ],
  complete: false,
  truncated: true,
};

function msal(): IPublicClientApplication {
  const acc: AccountInfo = {
    homeAccountId: "home-fed",
    environment: "login.example.invalid",
    tenantId: "test-tenant",
    username: "someone@example.invalid",
    localAccountId: "local",
    name: "Test User",
    idTokenClaims: { roles: ["Viewer"] },
  };
  const base = createStubMsalInstance() as unknown as Record<string, unknown>;
  return {
    ...base,
    getAllAccounts: () => [acc],
    getActiveAccount: () => acc,
  } as unknown as IPublicClientApplication;
}

let activeFetch: typeof fetch = () => Promise.reject(new Error("useApi() was not called"));
const seen: URL[] = [];

function useApi(respond: (url: URL) => Response): void {
  seen.length = 0;
  activeFetch = (input) => {
    const url = new URL(typeof input === "string" ? input : (input as Request).url);
    if (url.pathname !== "/api/v1/federation/summary") {
      return Promise.reject(new Error(`unexpected ${url.pathname}`));
    }
    seen.push(url);
    return Promise.resolve(respond(url));
  };
}

const json = (b: unknown, status = 200): Response =>
  new Response(JSON.stringify(b), {
    status,
    headers: { "content-type": status === 200 ? "application/json" : "application/problem+json" },
  });

function renderPage(search = "") {
  const client = createApiClient({
    baseUrl: API,
    getToken: () => Promise.resolve("test-credential"),
    fetchImpl: (input, init) => activeFetch(input, init),
    maxRetries: 0,
  });
  return render(
    <MsalProvider instance={msal()}>
      <QueryProvider client={client}>
        <MemoryRouter initialEntries={[`/federation${search}`]}>
          <FederationPage />
        </MemoryRouter>
      </QueryProvider>
    </MsalProvider>,
  );
}

describe("helpers", () => {
  it("groups totals by currency without combining them", () => {
    const groups = groupByCurrency(SUMMARY.totals);
    expect(groups.map(([c, t]) => [c, t.length])).toEqual([
      ["USD", 2],
      ["EUR", 1],
    ]);
  });
  it("renders a null amount as unknown, never 0", () => {
    expect(totalText({ kind: "invoiced", currency: "USD", amount: null, complete: false })).toBe(
      "unknown",
    );
    expect(totalText({ kind: "estimated", currency: "USD", amount: "1.00", complete: false })).toBe(
      "$1.00 (incomplete)",
    );
  });
});

describe("FederationPage", () => {
  it("lists every cell outcome and says denied and unavailable data is not included", async () => {
    useApi(() => json(SUMMARY));
    renderPage();
    const cells = await screen.findByTestId("cells-panel");
    expect(within(cells).getByTestId("cell-cell-a").getAttribute("data-state")).toBe("ok");
    expect(within(cells).getByTestId("cell-cell-b").textContent).toContain("denied");
    expect(within(cells).getByTestId("cell-cell-b").textContent).toContain("not included");
    expect(within(cells).getByTestId("cell-cell-c").textContent).toContain("unavailable");
    expect(within(cells).getByTestId("cell-cell-c").textContent).toContain("not included");
    expect(screen.getByTestId("incomplete-notice")).toBeTruthy();
  });

  it("shows incomplete and truncated badges", async () => {
    useApi(() => json(SUMMARY));
    renderPage();
    const complete = await screen.findByTestId("badge-complete");
    expect(complete.textContent).toBe("incomplete");
    expect(screen.getByTestId("badge-truncated").textContent).toBe("truncated");
    expect(screen.getByTestId("truncated-notice")).toBeTruthy();
  });

  it("shows complete and not truncated for a clean summary", async () => {
    useApi(() =>
      json({
        ...SUMMARY,
        cells: [{ cell_id: "cell-a", state: "ok" }],
        complete: true,
        truncated: false,
      }),
    );
    renderPage();
    const complete = await screen.findByTestId("badge-complete");
    expect(complete.textContent).toBe("complete");
    expect(screen.getByTestId("badge-truncated").textContent).toBe("not truncated");
    expect(screen.queryByTestId("incomplete-notice")).toBeNull();
  });

  it("keeps currencies in separate tables and never sums them", async () => {
    useApi(() => json(SUMMARY));
    renderPage();
    const usd = await screen.findByTestId("totals-USD");
    const eur = screen.getByTestId("totals-EUR");
    expect(usd.textContent).toContain("$100.00");
    expect(usd.textContent).toContain("unknown");
    expect(usd.textContent).not.toContain("€");
    expect(eur.textContent).toContain("€40.00");
    expect(screen.queryByText(/140\.00/)).toBeNull();
  });

  it("renders unknown domain counts as unknown", async () => {
    useApi(() => json(SUMMARY));
    renderPage();
    const domains = await screen.findByTestId("domains-panel");
    expect(within(domains).getAllByText("unknown").length).toBeGreaterThanOrEqual(2);
  });

  it("states the boundary and does not claim a cross-boundary merge", async () => {
    useApi(() => json(SUMMARY));
    renderPage();
    await screen.findByTestId("federation-body");
    const text = document.body.textContent ?? "";
    expect(text).toContain("boundary-test");
    expect(text).toContain("not merged");
  });

  it("sends the window and the chosen cell filter", async () => {
    useApi(() => json(SUMMARY));
    renderPage("?days=7");
    await screen.findByTestId("federation-body");
    expect(seen[0]?.searchParams.get("days")).toBe("7");
    expect(seen[0]?.searchParams.has("cells")).toBe(false);
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Cell"), "cell-a");
    await waitFor(() => expect(seen.at(-1)?.searchParams.get("cells")).toBe("cell-a"));
  });

  it("falls back to the default window for an out-of-range value", async () => {
    useApi(() => json(SUMMARY));
    renderPage("?days=9999");
    await screen.findByTestId("federation-body");
    expect(seen[0]?.searchParams.get("days")).toBe("30");
  });

  it("shows forbidden on 403 and error on 500", async () => {
    useApi(() => json({ code: "forbidden", correlation_id: "c1" }, 403));
    renderPage();
    expect(await screen.findByTestId("forbidden-state")).toBeTruthy();
    cleanup();
    useApi(() => json({ code: "internal", correlation_id: "c2" }, 500));
    renderPage();
    await waitFor(() => expect(screen.getByTestId("error-state")).toBeTruthy());
  });
});
