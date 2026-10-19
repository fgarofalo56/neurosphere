import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { AnalyticsChip, LagIndicator } from "../components";
import { STRINGS } from "../strings";
import { FRESH, ResizeObserverStub } from "./fixtures";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(cleanup);

describe("LagIndicator", () => {
  it("renders watermark, lag and billing freshness", () => {
    render(<LagIndicator freshness={FRESH} />);
    expect(screen.getByTestId("watermark").textContent).toBe("2026-10-19T10:00:00Z");
    expect(screen.getByTestId("lag").textContent).toBe("90 s");
    expect(screen.getByTestId("billing-freshness").textContent).toBe("2026-10-18T00:00:00Z");
    expect(screen.getByText(STRINGS.billingFreshnessLabel)).toBeTruthy();
  });

  it("treats a null watermark and null lag as unknown", () => {
    render(
      <LagIndicator
        freshness={{ watermark: null, lag_seconds: null, billing_source_freshness: null }}
      />,
    );
    expect(screen.getByTestId("watermark").textContent).toBe("unknown");
    expect(screen.getByTestId("lag").textContent).toBe("unknown");
    expect(screen.queryByTestId("billing-freshness")).toBeNull();
  });

  it("renders a zero lag as 0 s, not unknown", () => {
    render(<LagIndicator freshness={{ ...FRESH, lag_seconds: 0 }} />);
    expect(screen.getByTestId("lag").textContent).toBe("0 s");
  });
});

describe("AnalyticsChip", () => {
  it.each(["available", "delayed", "disabled"] as const)("renders the %s state", (state) => {
    render(<AnalyticsChip analytics={{ state, reason: null }} />);
    expect(screen.getByTestId("analytics-chip").textContent).toContain(
      STRINGS.analyticsState[state],
    );
  });

  it("shows the reason when disabled", () => {
    render(
      <AnalyticsChip analytics={{ state: "disabled", reason: "not enabled in this region" }} />,
    );
    expect(screen.getByTestId("analytics-reason").textContent).toContain(
      "not enabled in this region",
    );
  });

  it("names no vendor", () => {
    const all = JSON.stringify(STRINGS).toLowerCase();
    expect(all).not.toMatch(/fabric|synapse|databricks|azure|cosmos/);
  });
});
