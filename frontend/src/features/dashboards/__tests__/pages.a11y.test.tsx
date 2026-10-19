import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { ResizeObserverStub, costResponse, response, series, known, setupPage } from "./fixtures";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(cleanup);

const BODIES = {
  cost: costResponse(),
  latency: response("latency", {
    analytics: { state: "disabled", reason: "adapter not configured" },
    series: [series({ key: "p95", label: "p95 latency", unit: "ms", total: known(120) })],
  }),
  errors: response("errors", {
    series: [series({ key: "error_rate", label: "Error rate", unit: "ratio", total: known(0) })],
  }),
  coverage: response("coverage", {
    analytics: { state: "delayed", reason: "ingest lag" },
    series: [series({ key: "coverage", label: "Coverage", unit: "ratio", total: known(0.9) })],
  }),
};

describe.each([
  ["/dashboards/cost?domain_id=dom-1", "Cost"],
  ["/dashboards/latency?domain_id=dom-1", "Latency"],
  ["/dashboards/coverage?domain_id=dom-1", "Coverage"],
])("%s", (path, title) => {
  it("has no axe violations", async () => {
    const { container } = setupPage(path, BODIES);
    await screen.findAllByTestId("lag-indicator");
    const results = await axe(container);
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
    expect(screen.getByRole("heading", { level: 1, name: title })).toBeTruthy();
  });

  it("is keyboard navigable", async () => {
    const user = userEvent.setup();
    setupPage(path, BODIES);
    await screen.findAllByTestId("lag-indicator");
    await user.tab();
    expect(document.activeElement).toBe(screen.getByLabelText("Domain"));
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Apply" }));
    await user.tab();
    expect(document.activeElement).toBe(screen.getByLabelText("Days"));
    await user.tab();
    expect(document.activeElement).toBe(screen.getByLabelText("Grain"));
    await user.tab();
    const region = document.activeElement as HTMLElement;
    expect(region.getAttribute("role")).toBe("region");
  });
});

describe("controls and errors", () => {
  it("requests the contract path with domain_id, days and grain", async () => {
    const { fetchImpl } = setupPage("/dashboards/cost?domain_id=dom-1&days=7&grain=hour", BODIES);
    await screen.findAllByTestId("lag-indicator");
    const url = new URL(String(fetchImpl.mock.calls[0]?.[0]));
    expect(url.pathname).toBe("/api/v1/dashboards/cost");
    expect(url.searchParams.get("domain_id")).toBe("dom-1");
    expect(url.searchParams.get("days")).toBe("7");
    expect(url.searchParams.get("grain")).toBe("hour");
  });

  it("changing the grain to hour clamps days to 14", async () => {
    const user = userEvent.setup();
    const { fetchImpl } = setupPage("/dashboards/cost?domain_id=dom-1&days=60", BODIES);
    await screen.findAllByTestId("lag-indicator");
    await user.selectOptions(screen.getByLabelText("Grain"), "hour");
    await waitFor(() => {
      const last = new URL(String(fetchImpl.mock.calls.at(-1)?.[0]));
      expect(last.searchParams.get("days")).toBe("14");
      expect(last.searchParams.get("grain")).toBe("hour");
    });
  });

  it("asks for a domain and makes no request when none is selected", () => {
    const { fetchImpl } = setupPage("/dashboards/cost", BODIES);
    expect(screen.getByTestId("domain-required")).toBeTruthy();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("renders the forbidden state on 403", async () => {
    setupPage("/dashboards/cost?domain_id=dom-1", 403);
    await screen.findByTestId("forbidden-state");
  });

  it("renders an error state, not empty data, on 503", async () => {
    setupPage("/dashboards/cost?domain_id=dom-1", 503);
    await screen.findByTestId("error-state");
    expect(screen.queryByTestId("series-block")).toBeNull();
  });
});
