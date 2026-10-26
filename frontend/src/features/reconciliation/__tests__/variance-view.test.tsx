import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { QueryProvider, createApiClient } from "../../../api/index.js";
import { reconciliationRoutes } from "../routes";
import { STRINGS } from "../strings";
import type { MetricValue, ReconciliationResponse, SourceLine } from "../types";

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(cleanup);

const known = (value: number, complete = true): MetricValue => ({
  value,
  status: "known",
  complete,
  price_version: null,
});
const unknown = (): MetricValue => ({
  value: null,
  status: "unknown",
  complete: false,
  price_version: null,
});

const line = (over: Partial<SourceLine> & Pick<SourceLine, "source">): SourceLine => ({
  granularity: "request",
  amount: known(10),
  coverage: known(1),
  variance: known(0),
  currency: "USD",
  ...over,
});

function body(over: Partial<ReconciliationResponse> = {}): ReconciliationResponse {
  return {
    domain_id: "dom-1",
    window: { start: "2026-10-01T00:00:00Z", end: "2026-10-20T00:00:00Z" },
    freshness: {
      watermark: "2026-10-19T10:00:00Z",
      lag_seconds: 90,
      billing_source_freshness: null,
    },
    complete: false,
    truncated: false,
    reference: { label: "ledger (one record per request)", amount: known(10), currency: "USD" },
    references: [
      {
        label: "ledger (one record per request)",
        amount: known(10),
        currency: "USD",
        entry_count: 3,
        unknown_entry_count: 1,
      },
    ],
    sources: [
      line({ source: "gateway", amount: known(9), variance: known(-1) }),
      line({
        source: "app",
        granularity: "unknown",
        amount: unknown(),
        coverage: unknown(),
        variance: unknown(),
      }),
      line({
        source: "billing",
        granularity: "vendor",
        amount: known(4),
        coverage: unknown(),
        variance: known(-6),
      }),
    ],
    unknown_remainder: { ...known(1), unit: "entries" },
    disclaimer: "not_all_spend_observable",
    ...over,
  };
}

function setup(path: string, reply: ReconciliationResponse | number) {
  const fetchImpl = vi.fn<typeof fetch>(() =>
    Promise.resolve(
      typeof reply === "number"
        ? new Response(JSON.stringify({ status: reply }), { status: reply })
        : new Response(JSON.stringify(reply), { status: 200 }),
    ),
  );
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("t"),
    fetchImpl,
    maxRetries: 0,
  });
  const router = createMemoryRouter(reconciliationRoutes, { initialEntries: [path] });
  const view = render(
    <QueryProvider client={client}>
      <RouterProvider router={router} />
    </QueryProvider>,
  );
  return { fetchImpl, ...view };
}

const PATH = "/reconciliation?domain_id=dom-1";

describe("reconciliation view", () => {
  it("shows a visible granularity label per source", async () => {
    setup(PATH, body());
    await screen.findByTestId("reference-row");
    const text = (id: string) => within(screen.getByTestId(id)).getByTestId("granularity");
    expect(text("source-gateway").textContent).toBe(STRINGS.granularity.request);
    expect(text("source-billing").textContent).toBe(STRINGS.granularity.vendor);
    expect(text("source-app").textContent).toBe(STRINGS.granularity.unknown);
  });

  it("renders unknown coverage, amount and variance as exactly 'unknown'", async () => {
    setup(PATH, body());
    const app = within(await screen.findByTestId("source-app"));
    expect(app.getByTestId("coverage").textContent).toBe("unknown");
    expect(app.getByTestId("amount").textContent).toBe("unknown");
    expect(app.getByTestId("variance").textContent).toBe("unknown");
    const billing = within(screen.getByTestId("source-billing"));
    expect(billing.getByTestId("coverage").textContent).toBe("unknown");
    expect(billing.getByTestId("coverage").textContent).not.toContain("0%");
    expect(within(screen.getByTestId("source-gateway")).getByTestId("coverage").textContent).toBe(
      "100%",
    );
  });

  it("shows the reference row, unknown remainder, freshness and the notice", async () => {
    setup(PATH, body());
    const ref = within(await screen.findByTestId("reference-row"));
    expect(ref.getByTestId("reference-amount").textContent).toBe("10 USD");
    expect(screen.getByTestId("disclaimer").textContent).toBe(STRINGS.disclaimer);
    expect(screen.getByTestId("unknown-remainder").textContent).toContain(
      `${STRINGS.unknownRemainderLabel}: 1`,
    );
    // A Timestamp: the raw ISO rides in `datetime`, never as visible text.
    const watermark = screen.getByTestId("watermark").querySelector("time");
    expect(watermark?.getAttribute("datetime")).toBe("2026-10-19T10:00:00.000Z");
    expect(screen.getByTestId("watermark").textContent).not.toContain("2026-10-19T10:00:00");
    expect(screen.getByTestId("lag").textContent).toBe("90 s");
    expect(screen.getByTestId("billing-freshness").textContent).toBe("unknown");
    expect(screen.getByTestId("incomplete-data")).toBeTruthy();
  });

  it("keeps currencies in separate tables", async () => {
    const eur = { ...line({ source: "gateway", currency: "EUR" }) };
    setup(
      PATH,
      body({
        references: [
          {
            label: "ledger (one record per request)",
            amount: known(10),
            currency: "USD",
            entry_count: 1,
            unknown_entry_count: 0,
          },
          {
            label: "ledger (one record per request)",
            amount: known(7),
            currency: "EUR",
            entry_count: 1,
            unknown_entry_count: 0,
          },
        ],
        sources: [line({ source: "gateway" }), eur],
      }),
    );
    await waitFor(() => expect(screen.getAllByTestId("currency-section")).toHaveLength(2));
  });

  it("has no axe violations", async () => {
    const { container } = setup(PATH, body());
    await screen.findByTestId("reference-row");
    const results = await axe(container);
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });

  it("requests the domain as a path segment with days as a query param", async () => {
    const { fetchImpl } = setup("/reconciliation?domain_id=a%2Fb&days=7", body());
    await screen.findByTestId("reference-row");
    const url = String(fetchImpl.mock.calls[0]?.[0]);
    expect(url).toContain("/api/v1/reconciliation/domains/a%2Fb");
    expect(url).toContain("days=7");
    expect(url).not.toContain("domain_id");
    expect(url).not.toContain("customer_id");
  });

  it("shows the forbidden state on 403, not empty data", async () => {
    setup(PATH, 403);
    expect(await screen.findByTestId("forbidden-state")).toBeTruthy();
    expect(screen.queryByTestId("reconciliation-view")).toBeNull();
  });

  it("asks for a domain and makes no request without one", () => {
    const { fetchImpl } = setup("/reconciliation", body());
    expect(screen.getByTestId("domain-required")).toBeTruthy();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("shows a loading state first, then an error state (not empty data) on 503", async () => {
    setup(PATH, 503);
    expect(screen.getByLabelText(STRINGS.loading)).toBeTruthy();
    expect(await screen.findByTestId("error-state")).toBeTruthy();
    expect(screen.queryByTestId("reconciliation-view")).toBeNull();
  });

  it("shows an empty state when there are no references", async () => {
    setup(PATH, body({ references: [], sources: [] }));
    expect(await screen.findByTestId("no-data")).toBeTruthy();
    expect(screen.queryAllByTestId("currency-section")).toHaveLength(0);
  });

  it("charts coverage per source with unknown as a gap, never a zero-height bar", async () => {
    setup(PATH, body());
    const card = within(await screen.findByTestId("currency-section"));
    // Gateway is known (100%); app and billing are unknown.
    expect(card.getByRole("img").getAttribute("aria-label")).toContain(STRINGS.coverageChartLabel);
    expect(card.getAllByTestId("gap-marker")).toHaveLength(2);
  });

  it("says coverage is unknown, instead of charting zeros, when no source reports it", async () => {
    const unknownCoverage = (source: SourceLine["source"]) => line({ source, coverage: unknown() });
    setup(
      PATH,
      body({
        sources: [unknownCoverage("gateway"), unknownCoverage("app"), unknownCoverage("billing")],
      }),
    );
    const card = within(await screen.findByTestId("currency-section"));
    expect(card.getByTestId("coverage-empty")).toBeTruthy();
    expect(card.queryByRole("img")).toBeNull();
  });
});
