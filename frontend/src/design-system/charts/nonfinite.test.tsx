import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AppThemeProvider } from "../AppThemeProvider";
import { Sparkline, TimeSeriesChart } from "./index";
import type { ChartSeries } from "./index";

afterEach(cleanup);

const day = (d: number): string => `2026-03-${String(d).padStart(2, "0")}T00:00:00Z`;

function costSeries(values: number[]): ChartSeries {
  return {
    key: "cost",
    label: "Cost",
    kind: "invoiced",
    unit: "currency",
    currency: "USD",
    points: values.map((value, i) => ({ t: day(i + 1), value })),
  };
}

describe("non-finite values", () => {
  it("NaN and Infinity are unknown, like null", () => {
    render(
      <AppThemeProvider>
        <TimeSeriesChart series={[costSeries([10, Number.NaN, 30, Number.POSITIVE_INFINITY])]} />
      </AppThemeProvider>,
    );
    const d = screen.getByTestId("line-cost").getAttribute("d") ?? "";
    expect(d).not.toContain("NaN");
    expect(d).not.toContain("Infinity");
    expect(d.split("M").length - 1).toBe(2);
    expect(screen.getAllByTestId("gap-marker")).toHaveLength(2);
  });

  it("sparkline summary formats with unit and currency", () => {
    render(
      <AppThemeProvider>
        <Sparkline values={[1200, 3400]} label="Cost" unit="currency" currency="USD" />
      </AppThemeProvider>,
    );
    const name = screen.getByRole("img").getAttribute("aria-label") ?? "";
    expect(name).toContain("min $1,200.00");
    expect(name).toContain("max $3,400.00");
  });
});
