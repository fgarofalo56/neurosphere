import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { groupSeries, groupTitle, toChartSeries } from "../chartData";
import { totalText } from "../DashboardPage";
import { STRINGS } from "../strings";
import {
  PV,
  ResizeObserverStub,
  costResponse,
  known,
  response,
  series,
  setupPage,
  unknownMetric,
} from "./fixtures";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(cleanup);

const eurEstimated = series({
  key: "estimated-eur",
  label: "Estimated cost EUR",
  kind: "estimated",
  unit: "currency",
  currency: "EUR",
  total: known(40, PV),
  points: [
    { t: "2026-10-17", value: known(10, PV) },
    { t: "2026-10-18", value: known(30, PV) },
  ],
});

function multiCurrency() {
  const base = costResponse();
  return { ...base, series: [...base.series, eurEstimated] };
}

describe("chart data mapping", () => {
  it("maps an unknown point to null, never 0, and a real zero stays 0", () => {
    const mapped = toChartSeries(multiCurrency().series[0] as never);
    expect(mapped.points.map((p) => p.value)).toEqual([0, null, 12.5]);
  });

  it("carries the incomplete flag so the chart can mark partial data", () => {
    const partial = series({
      key: "p",
      unit: "currency",
      currency: "USD",
      points: [{ t: "2026-10-17", value: { ...known(3), complete: false } }],
    });
    expect(toChartSeries(partial).points[0]?.complete).toBe(false);
  });

  it("groups by unit and currency: estimated and invoiced of one currency share a group", () => {
    const groups = groupSeries(multiCurrency().series);
    expect(groups.map((g) => g.key)).toEqual(["currency:USD", "currency:EUR"]);
    expect(groups[0]?.series.map((s) => s.key)).toEqual(["estimated-usd", "invoiced-usd"]);
    expect(groups[1]?.series.map((s) => s.key)).toEqual(["estimated-eur"]);
    expect(groups.map((g) => groupTitle(g, "cost"))).toEqual(["Cost in USD", "Cost in EUR"]);
  });

  it("never groups different units together", () => {
    const groups = groupSeries([
      series({ key: "a", unit: "ms" }),
      series({ key: "b", unit: "ratio" }),
      series({ key: "c", unit: "ms" }),
    ]);
    expect(groups.map((g) => [g.key, g.series.length])).toEqual([
      ["ms", 2],
      ["ratio", 1],
    ]);
  });

  it("formats a total in its own unit and shows unknown as unknown", () => {
    expect(totalText(multiCurrency().series[1] as never)).toBe("$20.00");
    expect(
      totalText(series({ key: "u", unit: "currency", currency: "EUR", total: unknownMetric() })),
    ).toBe(STRINGS.unknown);
    expect(totalText(series({ key: "r", unit: "ratio", total: known(0.9) }))).toBe("90%");
    expect(totalText(series({ key: "z", unit: "count", total: known(0) }))).toBe("0");
  });
});

describe("cost dashboard charts", () => {
  it("draws one chart per currency and never sums currencies", async () => {
    setupPage("/dashboards/cost?domain_id=dom-1", { cost: multiCurrency() });
    const panels = await screen.findAllByTestId("chart-panel");
    expect(panels).toHaveLength(2);
    const [usd, eur] = panels as [HTMLElement, HTMLElement];
    expect(within(usd).getByRole("heading", { name: "Cost in USD" })).toBeTruthy();
    expect(within(eur).getByRole("heading", { name: "Cost in EUR" })).toBeTruthy();
    // Estimated and invoiced of the same currency are drawn together but as distinct lines.
    expect(within(usd).getByTestId("line-estimated-usd")).toBeTruthy();
    expect(within(usd).getByTestId("line-invoiced-usd")).toBeTruthy();
    expect(within(usd).queryByTestId("line-estimated-eur")).toBeNull();
    expect(within(eur).getByTestId("line-estimated-eur")).toBeTruthy();
    // No cross-currency total is anywhere on the page (12.5 + 20 + 40 = 72.5).
    expect(document.body.textContent).not.toMatch(/72\.5|\$72|€72/);
  });

  it("marks an unknown day as a gap in the chart, not as a zero point", async () => {
    setupPage("/dashboards/cost?domain_id=dom-1", { cost: costResponse() });
    const [usd] = (await screen.findAllByTestId("chart-panel")) as [HTMLElement];
    expect(within(usd).getAllByTestId("gap-marker")).toHaveLength(1);
  });

  it("keeps the accessible data table next to every chart", async () => {
    setupPage("/dashboards/cost?domain_id=dom-1", { cost: multiCurrency() });
    await screen.findAllByTestId("chart-panel");
    expect(screen.getByRole("region", { name: "Estimated cost USD data table" })).toBeTruthy();
    expect(screen.getByRole("table", { name: "Estimated cost EUR" })).toBeTruthy();
  });
});

describe("dashboard states", () => {
  it("shows an empty state, not a zero, when the API returns no series", async () => {
    setupPage("/dashboards/cost?domain_id=dom-1", { cost: response("cost") });
    expect(await screen.findByText(STRINGS.emptyTitle)).toBeTruthy();
    expect(screen.queryAllByTestId("series-block")).toHaveLength(0);
    expect(screen.queryAllByTestId("chart-panel")).toHaveLength(0);
  });

  it("shows a loading state before the data arrives", () => {
    setupPage("/dashboards/cost?domain_id=dom-1", { cost: response("cost") });
    expect(screen.getByLabelText(`${STRINGS.loadingLabel} cost`)).toBeTruthy();
  });

  it("shows an empty chart state when a series has no points", async () => {
    setupPage("/dashboards/latency?domain_id=dom-1", {
      latency: response("latency", {
        series: [series({ key: "p95", label: "p95 latency", unit: "ms", points: [] })],
      }),
      errors: response("errors"),
    });
    expect(await screen.findByText(STRINGS.chartEmpty)).toBeTruthy();
  });
});
