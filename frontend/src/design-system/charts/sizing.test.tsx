/// <reference types="vite/client" />
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppThemeProvider } from "../AppThemeProvider";
import { BarChart, TimeSeriesChart } from "./index";
import type { ChartSeries } from "./index";

const series: ChartSeries = {
  key: "cost",
  label: "Cost",
  kind: "invoiced",
  unit: "currency",
  currency: "USD",
  points: Array.from({ length: 30 }, (_, i) => ({
    t: `2026-03-${String(i + 1).padStart(2, "0")}T00:00:00Z`,
    value: 10 + i,
    complete: true,
  })),
};

/** Stubs ResizeObserver so observing reports the given container width. */
function stubObserver(widthPx: number): void {
  class FakeObserver {
    constructor(private readonly cb: (entries: unknown[]) => void) {}
    observe(): void {
      this.cb([{ contentRect: { width: widthPx } }]);
    }
    disconnect(): void {}
    unobserve(): void {}
  }
  vi.stubGlobal("ResizeObserver", FakeObserver);
}

function measure(widthPx: number, bar = false) {
  stubObserver(widthPx);
  const { container } = render(
    <AppThemeProvider>
      {bar ? <BarChart series={[series]} /> : <TimeSeriesChart series={[series]} />}
    </AppThemeProvider>,
  );
  const svg = container.querySelector("svg") as SVGSVGElement;
  const texts = [...svg.querySelectorAll("text")];
  const xLabels = texts.filter((t) => t.getAttribute("text-anchor") === "middle");
  const result = {
    svg,
    fontSizes: new Set(texts.map((t) => t.getAttribute("font-size"))),
    xLabelCount: xLabels.length,
  };
  return result;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("chart pixel sizing", () => {
  it("renders at the measured width with the height prop unchanged", () => {
    const wide = measure(1200);
    expect(wide.svg.getAttribute("width")).toBe("1200");
    expect(wide.svg.getAttribute("height")).toBe("240");
    expect(wide.svg.getAttribute("viewBox")).toBe("0 0 1200 240");
  });

  it("keeps label font size constant across container widths", () => {
    const wide = measure(1200);
    cleanup();
    const narrow = measure(400);
    expect([...wide.fontSizes]).toEqual(["11"]);
    expect([...narrow.fontSizes]).toEqual(["11"]);
    expect(narrow.svg.getAttribute("height")).toBe(wide.svg.getAttribute("height"));
  });

  it("draws fewer x ticks when narrow (time series and bar)", () => {
    const wide = measure(1200);
    cleanup();
    const narrow = measure(400);
    expect(narrow.xLabelCount).toBeLessThan(wide.xLabelCount);
    cleanup();
    const wideBar = measure(1200, true);
    cleanup();
    const narrowBar = measure(400, true);
    expect(narrowBar.xLabelCount).toBeLessThan(wideBar.xLabelCount);
  });

  it("falls back to the width prop when nothing can be measured (jsdom)", () => {
    const { container } = render(
      <AppThemeProvider>
        <TimeSeriesChart series={[series]} width={500} height={200} />
      </AppThemeProvider>,
    );
    const svg = container.querySelector("svg") as SVGSVGElement;
    expect(svg.getAttribute("width")).toBe("500");
    expect(svg.getAttribute("height")).toBe("200");
  });

  it("ignores a zero measurement and keeps the fallback", () => {
    stubObserver(0);
    const { container } = render(
      <AppThemeProvider>
        <BarChart series={[series]} width={480} />
      </AppThemeProvider>,
    );
    expect(container.querySelector("svg")?.getAttribute("width")).toBe("480");
  });

  it("measures a chart that first rendered its error state and later gets valid series", () => {
    stubObserver(900);
    const eur: ChartSeries = { ...series, key: "eur", currency: "EUR" };
    const ui = (s: ChartSeries[]) => (
      <AppThemeProvider>
        <TimeSeriesChart series={s} />
      </AppThemeProvider>
    );
    const { container, rerender } = render(ui([series, eur]));
    expect(container.querySelector("svg")).toBeNull();
    rerender(ui([series]));
    expect(container.querySelector("svg")?.getAttribute("width")).toBe("900");
  });

  it("disconnects the observer on unmount", () => {
    const disconnect = vi.fn();
    class FakeObserver {
      observe(): void {}
      disconnect = disconnect;
      unobserve(): void {}
    }
    vi.stubGlobal("ResizeObserver", FakeObserver);
    const { unmount } = render(
      <AppThemeProvider>
        <TimeSeriesChart series={[series]} />
      </AppThemeProvider>,
    );
    unmount();
    expect(disconnect).toHaveBeenCalled();
  });
});
