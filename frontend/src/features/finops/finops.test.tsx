import type { AccountInfo, IPublicClientApplication } from "@azure/msal-browser";
import { MsalProvider } from "@azure/msal-react";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { QueryProvider, createApiClient } from "../../api/index.js";
import { createStubMsalInstance } from "../../../tests/e2e-support/stubMsal";
import { ForecastPage, amountText, chartSeries } from "./ForecastPage";
import type { Amount, CostSeries, ForecastResponse } from "./data";
import { pickOption } from "./data";
import { HISTORY_OPTIONS } from "./strings";

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

const known = (n: string, complete = true): Amount => ({
  value: n,
  status: "known",
  complete,
  reason: null,
});
const unknown: Amount = { value: null, status: "unknown", complete: false, reason: "metering_gap" };

function costSeries(kind: "estimated" | "invoiced", over: Partial<CostSeries> = {}): CostSeries {
  return {
    kind,
    currency: "USD",
    points: [
      { day: "2026-10-12", phase: "history", actual: known("10.00") },
      { day: "2026-10-13", phase: "history", actual: unknown },
      { day: "2026-10-14", phase: "history", actual: known("12.00", false) },
      {
        day: "2026-10-15",
        phase: "horizon",
        actual: unknown,
        forecast: { value: "13.00", lower: "11.00", upper: "15.00" },
      },
    ],
    summary: {
      history_actual: known(kind === "estimated" ? "22.00" : "31.00", false),
      horizon_actual: unknown,
      horizon_forecast: { value: "13.00", lower: "11.00", upper: "15.00" },
    },
    forecast_available: true,
    forecast_unavailable_reason: null,
    fit_points: 5,
    excluded_incomplete_days: 2,
    residual_std: "1.00",
    ...over,
  };
}

function body(over: Partial<ForecastResponse> = {}): ForecastResponse {
  return {
    domain_id: DOMAIN,
    as_of: "2026-10-15",
    method: {
      name: "linear_trend_ols",
      description: "Ordinary least squares trend.",
      confidence_level: "0.95",
      z: "1.96",
      min_fit_points: 7,
      history_days: 30,
      horizon_days: 14,
      savings_claim: false,
    },
    price_version_id: "pv-2026-10",
    price_version_ids: ["pv-2026-10", "pv-2026-09"],
    estimated: costSeries("estimated"),
    invoiced: costSeries("invoiced"),
    ...over,
  };
}

function account(): AccountInfo {
  return {
    homeAccountId: "home-finops",
    environment: "login.example.invalid",
    tenantId: "test-tenant",
    username: "someone@example.invalid",
    localAccountId: "local",
    name: "Test User",
    idTokenClaims: { roles: ["Viewer"] },
  };
}

function msal(): IPublicClientApplication {
  const acc = account();
  const base = createStubMsalInstance() as unknown as Record<string, unknown>;
  return {
    ...base,
    getAllAccounts: () => [acc],
    getActiveAccount: () => acc,
  } as unknown as IPublicClientApplication;
}

let activeFetch: typeof fetch = () => Promise.reject(new Error("useApi() was not called"));
const seen: URL[] = [];

/** Strict fake API: only the forecast path is answered; anything else rejects. */
function useApi(respond: (url: URL) => Response): void {
  seen.length = 0;
  const expected = `/api/v1/finops/domains/${encodeURIComponent(DOMAIN)}/forecast`;
  activeFetch = (input) => {
    const url = new URL(typeof input === "string" ? input : (input as Request).url);
    if (url.pathname !== expected) return Promise.reject(new Error(`unexpected ${url.pathname}`));
    seen.push(url);
    return Promise.resolve(respond(url));
  };
}

const json = (b: unknown, status = 200): Response =>
  new Response(JSON.stringify(b), {
    status,
    headers: { "content-type": status === 200 ? "application/json" : "application/problem+json" },
  });

function renderPage(search = `?domain_id=${encodeURIComponent(DOMAIN)}`) {
  const client = createApiClient({
    baseUrl: API,
    getToken: () => Promise.resolve("test-credential"),
    fetchImpl: (input, init) => activeFetch(input, init),
    maxRetries: 0,
  });
  return render(
    <MsalProvider instance={msal()}>
      <QueryProvider client={client}>
        <MemoryRouter initialEntries={[`/finops/forecast${search}`]}>
          <ForecastPage />
        </MemoryRouter>
      </QueryProvider>
    </MsalProvider>,
  );
}

describe("amountText", () => {
  it("renders unknown as the word, never 0", () => {
    expect(amountText(unknown, "USD")).toBe("unknown");
    expect(amountText({ ...unknown, value: null }, "USD")).not.toContain("0");
  });
  it("flags an incomplete figure", () => {
    expect(amountText(known("12.00", false), "USD")).toBe("$12.00 (incomplete)");
    expect(amountText(known("12.00"), "USD")).toBe("$12.00");
  });
});

describe("pickOption", () => {
  it("falls back to the default outside the allowed set", () => {
    expect(pickOption("999", HISTORY_OPTIONS, 30)).toBe(30);
    expect(pickOption("14", HISTORY_OPTIONS, 30)).toBe(14);
    expect(pickOption(null, HISTORY_OPTIONS, 30)).toBe(30);
  });
});

describe("chartSeries", () => {
  it("plots unknown as null and adds two bound series when a forecast exists", () => {
    const out = chartSeries(costSeries("estimated"));
    expect(out.map((s) => s.key)).toEqual([
      "estimated-actual",
      "estimated-forecast",
      "estimated-lower",
      "estimated-upper",
    ]);
    const actual = out[0]?.points ?? [];
    expect(actual.find((p) => p.t.startsWith("2026-10-13"))?.value).toBeNull();
    expect(actual.find((p) => p.t.startsWith("2026-10-14"))?.complete).toBe(false);
    // One unit, one currency per chart.
    expect(new Set(out.map((s) => s.currency))).toEqual(new Set(["USD"]));
  });
  it("draws no bounds when the forecast is unavailable", () => {
    const out = chartSeries(costSeries("invoiced", { forecast_available: false }));
    expect(out).toHaveLength(1);
  });
});

describe("ForecastPage", () => {
  it("shows estimated and invoiced separately with no combined total", async () => {
    useApi(() => json(body()));
    renderPage();
    const est = await screen.findByTestId("series-estimated");
    const inv = screen.getByTestId("series-invoiced");
    expect(within(est).getAllByText(/\$22\.00 \(incomplete\)/).length).toBeGreaterThan(0);
    expect(within(inv).getAllByText(/\$31\.00 \(incomplete\)/).length).toBeGreaterThan(0);
    // 22 + 31 is never shown.
    expect(screen.queryByText(/\$53\.00/)).toBeNull();
    expect(screen.getByTestId("chart-estimated")).toBeTruthy();
    expect(screen.getByTestId("chart-invoiced")).toBeTruthy();
    expect(screen.getByTestId("incomplete-estimated")).toBeTruthy();
  });

  it("renders unknown amounts as the word unknown", async () => {
    useApi(() => json(body()));
    renderPage();
    const est = await screen.findByTestId("series-estimated");
    expect(within(est).getAllByText("unknown").length).toBeGreaterThan(0);
    expect(within(est).queryByText("$0.00")).toBeNull();
  });

  it("shows the method card, fit points, excluded days and price versions", async () => {
    useApi(() => json(body()));
    renderPage();
    await screen.findByTestId("method-card");
    expect(screen.getByTestId("method-name").textContent).toBe("linear_trend_ols");
    expect(screen.getByTestId("method-confidence").textContent).toBe("95%");
    expect(screen.getByTestId("method-excluded").textContent).toContain("2");
    const versions = screen.getByTestId("price-versions");
    expect(within(versions).getByText("pv-2026-10")).toBeTruthy();
    expect(within(versions).getByText("pv-2026-09")).toBeTruthy();
    expect(screen.getByTestId("no-claim")).toBeTruthy();
  });

  it("offers a table alternative with lower and upper bound columns", async () => {
    useApi(() => json(body()));
    renderPage();
    const table = await screen.findByTestId("table-estimated");
    expect(within(table).getAllByText("Lower bound").length).toBeGreaterThan(0);
    expect(within(table).getAllByText("Upper bound").length).toBeGreaterThan(0);
    expect(screen.getByTestId("band-estimated").textContent).toContain("dashed");
  });

  it("states 'forecast unavailable: <reason>' and draws no bounds", async () => {
    useApi(() =>
      json(
        body({
          estimated: costSeries("estimated", {
            forecast_available: false,
            forecast_unavailable_reason: "insufficient_complete_history",
            points: [{ day: "2026-10-12", phase: "history", actual: known("10.00") }],
            summary: {
              history_actual: known("10.00"),
              horizon_actual: unknown,
              horizon_forecast: null,
            },
          }),
        }),
      ),
    );
    renderPage();
    const box = await screen.findByTestId("forecast-unavailable-estimated");
    expect(box.textContent).toContain("forecast unavailable: insufficient_complete_history");
    expect(screen.queryByTestId("band-estimated")).toBeNull();
    // The invoiced series still has its forecast.
    expect(screen.getByTestId("band-invoiced")).toBeTruthy();
  });

  it("sends only bounded parameters", async () => {
    useApi(() => json(body()));
    renderPage(`?domain_id=${encodeURIComponent(DOMAIN)}&history_days=9999&currency=EUR`);
    await screen.findByTestId("series-estimated");
    const url = seen[0];
    expect(url?.searchParams.get("history_days")).toBe("30");
    expect(url?.searchParams.get("horizon_days")).toBe("14");
    expect(url?.searchParams.get("currency")).toBe("EUR");
    expect(url?.searchParams.has("domain_id")).toBe(false);
  });

  it("shows the forbidden state on 403 and an error state on 500", async () => {
    useApi(() => json({ code: "forbidden", correlation_id: "c1" }, 403));
    renderPage();
    expect(await screen.findByTestId("forbidden-state")).toBeTruthy();
    cleanup();
    useApi(() => json({ code: "internal", correlation_id: "c2" }, 500));
    renderPage();
    await waitFor(() => expect(screen.getByTestId("error-state")).toBeTruthy());
  });

  it("asks for a domain when none is selected", () => {
    useApi(() => json(body()));
    renderPage("");
    expect(screen.getByTestId("domain-required")).toBeTruthy();
    expect(seen).toHaveLength(0);
  });
});

describe("wording", () => {
  it("never mentions savings in feature source (the API field name is excluded)", () => {
    const sources = import.meta.glob(["./*.ts", "./*.tsx", "!./*.test.*"], {
      query: "?raw",
      import: "default",
      eager: true,
    }) as Record<string, string>;
    expect(Object.keys(sources).length).toBeGreaterThan(3);
    for (const [path, src] of Object.entries(sources)) {
      const text = src.split("savings_claim").join("").toLowerCase();
      expect(text.includes("saving"), path).toBe(false);
    }
  });
});
