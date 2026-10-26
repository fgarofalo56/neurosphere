/// <reference types="vite/client" />
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { AppThemeProvider } from "../AppThemeProvider";
import { useThemeStore } from "../theme-store";
import type { ThemeName } from "../tokens";
import { BarChart, ChartLegend, MixedSeriesError, Sparkline, TimeSeriesChart } from "./index";
import { assertSingleUnitAndCurrency } from "./validate";
import type { ChartSeries } from "./index";

const day = (d: number): string => `2026-03-${String(d).padStart(2, "0")}T00:00:00Z`;

function series(
  over: Partial<ChartSeries> & { values?: (number | null)[]; incomplete?: number[] } = {},
): ChartSeries {
  const { values = [10, 20, 30, 25], incomplete = [], ...rest } = over;
  return {
    key: "cost",
    label: "Cost",
    kind: "invoiced",
    unit: "currency",
    currency: "USD",
    points: values.map((value, i) => ({ t: day(i + 1), value, complete: !incomplete.includes(i) })),
    ...rest,
  };
}

beforeEach(() => {
  useThemeStore.setState({ themeName: "light" });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("MixedSeriesError", () => {
  it("is thrown for mixed units", () => {
    expect(() =>
      assertSingleUnitAndCurrency([series(), series({ key: "l", unit: "ms", currency: null })]),
    ).toThrow(MixedSeriesError);
  });
  it("is thrown for mixed currencies", () => {
    expect(() =>
      assertSingleUnitAndCurrency([series(), series({ key: "e", currency: "EUR" })]),
    ).toThrow(/currencies/);
  });
  it("accepts one unit and one currency", () => {
    expect(() =>
      assertSingleUnitAndCurrency([series(), series({ key: "b", kind: "estimated" })]),
    ).not.toThrow();
  });
  it("renders an alert instead of a chart", () => {
    const { container } = render(
      <TimeSeriesChart series={[series(), series({ key: "e", currency: "EUR" })]} />,
    );
    expect(screen.getByRole("alert").textContent).toMatch(/mixed currencies/);
    expect(container.querySelector("svg")).toBeNull();
  });
  it("bar chart renders the alert too", () => {
    render(<BarChart series={[series(), series({ key: "l", unit: "count", currency: null })]} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});

describe("unknown values", () => {
  it("break the line and never plot as zero", () => {
    render(<TimeSeriesChart series={[series({ values: [10, null, 30, 40] })]} />);
    const d = screen.getByTestId("line-cost").getAttribute("d") ?? "";
    expect(d.match(/M/g)).toHaveLength(2);
    expect(d).not.toMatch(/ 0 /);
    const ys = [...d.matchAll(/[ML]\S+ (\S+)/g)].map((m) => Number(m[1]));
    expect(ys).toHaveLength(3);
    // The y of a zero value is the baseline (the largest y); no vertex may sit there.
    for (const y of ys) expect(y).toBeLessThan(240 - 28);
    expect(screen.getAllByTestId("gap-marker")).toHaveLength(1);
  });
  it("an all-unknown series draws no path data", () => {
    render(<TimeSeriesChart series={[series({ values: [null, null] })]} />);
    expect(screen.getByTestId("line-cost").getAttribute("d")).toBe("");
    expect(screen.getAllByTestId("gap-marker")).toHaveLength(2);
  });
  it("sparkline breaks on null", () => {
    render(<Sparkline values={[1, null, 3]} label="Cost" />);
    expect(screen.getByTestId("sparkline-path").getAttribute("d")?.match(/M/g)).toHaveLength(2);
    expect(screen.getAllByTestId("sparkline-gap")).toHaveLength(1);
  });
  it("bar chart draws no bar for unknown", () => {
    render(<BarChart series={[series({ values: [5, null, 7] })]} />);
    expect(screen.getAllByTestId("bar-cost")).toHaveLength(2);
    expect(screen.getAllByTestId("gap-marker")).toHaveLength(1);
  });
  it("incomplete points get a hollow marker", () => {
    render(<TimeSeriesChart series={[series({ incomplete: [2] })]} />);
    const marker = screen.getByTestId("incomplete-marker");
    expect(marker.getAttribute("fill")).toBe("none");
  });
});

describe("estimated versus invoiced", () => {
  it("dashes estimated and keeps invoiced solid", () => {
    render(
      <TimeSeriesChart
        series={[
          series({ key: "inv", kind: "invoiced" }),
          series({ key: "est", kind: "estimated" }),
        ]}
      />,
    );
    expect(screen.getByTestId("line-est").getAttribute("stroke-dasharray")).toBeTruthy();
    expect(screen.getByTestId("line-inv").getAttribute("stroke-dasharray")).toBeNull();
  });
  it("legend names the basis in words", () => {
    render(
      <ChartLegend
        series={[
          series({ key: "inv", kind: "invoiced" }),
          series({ key: "est", kind: "estimated", label: "Forecast" }),
        ]}
      />,
    );
    expect(screen.getByText("Cost (invoiced)")).toBeInTheDocument();
    expect(screen.getByText("Forecast (estimated)")).toBeInTheDocument();
  });
});

describe("accessibility and tooltip", () => {
  it("is role=img with a generated summary", () => {
    render(<TimeSeriesChart series={[series({ values: [10, null, 30, 25] })]} />);
    const label = screen.getByRole("img").getAttribute("aria-label") ?? "";
    expect(label).toContain("Cost (invoiced)");
    expect(label).toContain("Mar 1, 2026 to Mar 4, 2026");
    expect(label).toContain("min $10.00");
    expect(label).toContain("max $30.00");
    expect(label).toContain("latest $25.00");
    expect(label).toContain("1 unknown");
  });
  it("shows value, basis and date on pointer move", () => {
    render(<TimeSeriesChart series={[series({ kind: "estimated" })]} />);
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.pointerMove(screen.getByRole("img"), { clientX: 0 });
    const tip = screen.getByRole("tooltip");
    expect(tip.textContent).toContain("Mar 1, 2026");
    expect(tip.textContent).toContain("estimated");
    expect(tip.textContent).toContain("$10.00");
    fireEvent.pointerLeave(screen.getByRole("img"));
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
  it("tooltip says unknown, not zero, for a null point", () => {
    render(<TimeSeriesChart series={[series({ values: [null, 2] })]} />);
    fireEvent.pointerMove(screen.getByRole("img"), { clientX: 0 });
    expect(screen.getByRole("tooltip").textContent).toContain("unknown");
  });
  it("formats percent, ms and count units", () => {
    render(
      <>
        <TimeSeriesChart
          series={[series({ key: "r", unit: "ratio", currency: null, values: [0.25, 0.5] })]}
        />
        <TimeSeriesChart
          series={[series({ key: "m", unit: "ms", currency: null, values: [120, 240] })]}
        />
      </>,
    );
    const labels = screen.getAllByRole("img").map((el) => el.getAttribute("aria-label"));
    expect(labels[0]).toContain("25%");
    expect(labels[1]).toContain("120 ms");
  });
});

describe("reduced motion", () => {
  function stubMotion(noPreference: boolean): void {
    vi.stubGlobal("matchMedia", (q: string) => ({
      matches: q.includes("no-preference") ? noPreference : !noPreference,
      media: q,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }));
  }
  it("is off when matchMedia is missing (jsdom)", () => {
    render(<TimeSeriesChart series={[series()]} />);
    expect(screen.getByRole("img").getAttribute("data-motion")).toBe("off");
    expect((screen.getByTestId("line-cost") as unknown as SVGElement).style.transition).toBe("");
  });
  it("is off under prefers-reduced-motion: reduce", () => {
    stubMotion(false);
    render(<TimeSeriesChart series={[series()]} />);
    expect(screen.getByRole("img").getAttribute("data-motion")).toBe("off");
  });
  it("is on only under no-preference", () => {
    stubMotion(true);
    render(<TimeSeriesChart series={[series()]} />);
    expect(screen.getByRole("img").getAttribute("data-motion")).toBe("on");
    expect((screen.getByTestId("line-cost") as unknown as SVGElement).style.transition).toContain(
      "opacity",
    );
  });
});

describe("import boundary", () => {
  it("imports no vega, sigma or d3 and uses no raw HTML or eval", () => {
    const sources = import.meta.glob(["./**/*.ts", "./**/*.tsx", "!./**/*.test.*"], {
      query: "?raw",
      import: "default",
      eager: true,
    }) as Record<string, string>;
    expect(Object.keys(sources).length).toBeGreaterThan(5);
    const forbiddenImport =
      /from\s+["'](vega|sigma|d3)[^"']*["']|import\s*\(\s*["'](vega|sigma|d3)/;
    for (const [path, src] of Object.entries(sources)) {
      expect(forbiddenImport.test(src), path).toBe(false);
      expect(src.includes("dangerouslySetInnerHTML"), path).toBe(false);
      expect(/\beval\s*\(|new Function\(/.test(src), path).toBe(false);
      expect(/#[0-9a-fA-F]{3,8}\b/.test(src), path).toBe(false);
    }
  });
});

describe("axe in every theme", () => {
  const themes: ThemeName[] = ["light", "dark", "high-contrast"];
  for (const name of themes) {
    it(`has no violations in ${name}`, async () => {
      useThemeStore.setState({ themeName: name });
      const { container } = render(
        <AppThemeProvider>
          <TimeSeriesChart
            variant="area"
            series={[
              series({ key: "inv", values: [10, null, 30, 25], incomplete: [3] }),
              series({ key: "est", kind: "estimated" }),
            ]}
          />
          <BarChart series={[series()]} />
          <Sparkline values={[1, 2, null, 4]} label="Cost, last 4 days" />
        </AppThemeProvider>,
      );
      // jsdom has no layout, so colour-contrast is covered by Playwright.
      const results = await axe(container, { rules: { "color-contrast": { enabled: false } } });
      expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
    });
  }
});
