import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { vi } from "vitest";
import { QueryProvider, createApiClient } from "../../../api/index.js";
import { dashboardRoutes } from "../routes";
import type {
  DashboardMetric,
  DashboardResponse,
  Freshness,
  MetricValue,
  PriceVersion,
  Series,
} from "../types";

// jsdom has no ResizeObserver, which Fluent MessageBar uses.
export class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

export const PV: PriceVersion = { id: "pv-2026-07", effective_date: "2026-07-01" };

export const known = (value: number, pv: PriceVersion | null = null): MetricValue => ({
  value,
  status: "known",
  complete: true,
  price_version: pv,
});
export const unknownMetric = (): MetricValue => ({
  value: null,
  status: "unknown",
  complete: true,
  price_version: null,
});

export const FRESH: Freshness = {
  watermark: "2026-10-19T10:00:00Z",
  lag_seconds: 90,
  billing_source_freshness: "2026-10-18T00:00:00Z",
};

export function series(over: Partial<Series> & Pick<Series, "key">): Series {
  return {
    label: over.key,
    kind: null,
    unit: "count",
    currency: null,
    total: known(1),
    points: [{ t: "2026-10-18", value: known(1) }],
    ...over,
  };
}

export function response(
  metric: DashboardMetric,
  over: Partial<DashboardResponse> = {},
): DashboardResponse {
  return {
    metric,
    domain_id: "dom-1",
    grain: "day",
    window: { start: "2026-10-01", end: "2026-10-19" },
    freshness: FRESH,
    analytics: { state: "available", reason: null },
    complete: true,
    truncated: false,
    series: [],
    price_versions: [PV],
    ...over,
  };
}

export const costResponse = (): DashboardResponse =>
  response("cost", {
    series: [
      series({
        key: "estimated-usd",
        label: "Estimated cost USD",
        kind: "estimated",
        unit: "currency",
        currency: "USD",
        total: { ...known(12.5, PV), complete: false },
        points: [
          { t: "2026-10-17", value: known(0, PV) },
          { t: "2026-10-18", value: unknownMetric() },
          { t: "2026-10-19", value: known(12.5, PV) },
        ],
      }),
      series({
        key: "invoiced-usd",
        label: "Invoiced cost USD",
        kind: "invoiced",
        unit: "currency",
        currency: "USD",
        total: known(20, PV),
        points: [{ t: "2026-10-17", value: known(20, PV) }],
      }),
    ],
  });

export function setupPage(
  path: string,
  bodies: Partial<Record<DashboardMetric, DashboardResponse>> | number,
) {
  const fetchImpl = vi.fn<typeof fetch>((input) => {
    if (typeof bodies === "number") {
      return Promise.resolve(new Response(JSON.stringify({ status: bodies }), { status: bodies }));
    }
    const metric = /dashboards\/domains\/[^/]+\/(\w+)/.exec(String(input))?.[1] as DashboardMetric;
    return Promise.resolve(new Response(JSON.stringify(bodies[metric]), { status: 200 }));
  });
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("t"),
    fetchImpl,
    maxRetries: 0,
  });
  const router = createMemoryRouter(dashboardRoutes, { initialEntries: [path] });
  const view = render(
    <QueryProvider client={client}>
      <RouterProvider router={router} />
    </QueryProvider>,
  );
  return { fetchImpl, ...view };
}
