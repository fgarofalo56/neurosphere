import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AppThemeProvider } from "../AppThemeProvider";
import { ChartLegend, TimeSeriesChart, BarChart } from "../charts";
import type { ChartSeries } from "../charts";
import { DataTable, EmptyState, ErrorState, KpiCard, LoadingState, StatusPill } from "./index";

afterEach(cleanup);

function wrap(ui: React.ReactElement): ReturnType<typeof render> {
  return render(<AppThemeProvider>{ui}</AppThemeProvider>);
}

describe("testId on primitives", () => {
  it("renders data-testid on every root and keeps data-slot", () => {
    wrap(
      <>
        <KpiCard label="Spend" value="$1" testId="kpi" />
        <StatusPill label="Ready" tone="info" testId="pill" />
        <EmptyState title="Nothing" testId="empty" />
        <LoadingState testId="loading" />
        <ErrorState title="Boom" testId="error" />
      </>,
    );
    expect(screen.getByTestId("kpi").getAttribute("data-slot")).toBe("kpi-card");
    expect(screen.getByTestId("pill").getAttribute("data-slot")).toBe("status-pill");
    expect(screen.getByTestId("empty").getAttribute("data-slot")).toBe("empty-state");
    expect(screen.getByTestId("loading").getAttribute("data-slot")).toBe("loading-state");
    expect(screen.getByTestId("error").getAttribute("data-slot")).toBe("error-state");
  });

  it("omits data-testid when not given", () => {
    wrap(<StatusPill label="Ready" />);
    expect(screen.getByText("Ready").hasAttribute("data-testid")).toBe(false);
  });
});

describe("DataTable getRowProps", () => {
  it("applies data-testid and data-* to each body row only", () => {
    const rows = [{ id: "a" }, { id: "b" }];
    wrap(
      <DataTable
        label="T"
        columns={[{ key: "id", header: "Id", render: (r) => r.id }]}
        rows={rows}
        getRowId={(r) => r.id}
        getRowProps={(r) => ({ "data-testid": `row-${r.id}`, "data-kind": "x" })}
      />,
    );
    expect(screen.getByTestId("row-a").getAttribute("data-kind")).toBe("x");
    expect(screen.getAllByTestId(/^row-/)).toHaveLength(2);
  });
});

describe("unclassified series legend", () => {
  const s = (kind: ChartSeries["kind"]): ChartSeries => ({
    key: "k",
    label: "Spend",
    kind,
    unit: "currency",
    currency: "USD",
    points: [
      { t: "2026-03-01T00:00:00Z", value: 1, complete: true },
      { t: "2026-03-02T00:00:00Z", value: 2, complete: true },
    ],
  });

  it("shows just the label for a null kind and the basis otherwise", () => {
    wrap(<ChartLegend series={[s(null)]} />);
    expect(screen.getByText("Spend")).toBeTruthy();
    expect(screen.queryByText(/unclassified/)).toBeNull();
    cleanup();
    wrap(<ChartLegend series={[s("estimated")]} />);
    expect(screen.getByText("Spend (estimated)")).toBeTruthy();
  });

  it("time series and bar charts show no unclassified wording", () => {
    const { container } = wrap(
      <>
        <TimeSeriesChart series={[s(null)]} />
        <BarChart series={[s(null)]} />
      </>,
    );
    expect(container.textContent).not.toMatch(/unclassified/);
    expect(container.innerHTML).not.toMatch(/aria-label="[^"]*unclassified/);
  });
});
