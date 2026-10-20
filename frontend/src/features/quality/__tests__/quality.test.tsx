import { cleanup, render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { QueryProvider, createApiClient } from "../../../api/index.js";
import { qualityNavItems, qualityRoutes } from "../index";
import type { PilotGroundedRate, QualityResponse, TrendPoint } from "../types";

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

const DOMAIN = "commercial:contoso:catalog:domain:finance";
const PATH = `/quality?domain_id=${encodeURIComponent(DOMAIN)}`;

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(cleanup);

function point(over: Partial<TrendPoint> = {}): TrendPoint {
  return {
    bucket_start: "2026-10-01T00:00:00Z",
    value: 0.82,
    lower: 0.7,
    upper: 0.91,
    level: 0.95,
    sample_size: 40,
    judge: {
      judge_kind: "llm_judge",
      judge_model_id: "commercial:contoso:foundry:model_deployment:judge-a",
      judge_model_version: "2026-08",
      judge_prompt_version: "p-3.1",
      program_version: null,
    },
    calibration_state: "calibrated",
    ...over,
  };
}

function pilot(over: Partial<PilotGroundedRate> = {}): PilotGroundedRate {
  return {
    value: 0.92,
    lower: 0.85,
    upper: 0.96,
    level: 0.95,
    n: 120,
    method: "wilson_score",
    target: 0.9,
    target_label: "pilot-set target: at least 90%",
    ...over,
  };
}

function quality(over: Partial<QualityResponse> = {}): QualityResponse {
  return {
    trends: [
      { dimension: "groundedness", points: [point()] },
      {
        dimension: "safety",
        points: [
          point({
            value: null,
            lower: null,
            upper: null,
            level: null,
            sample_size: 0,
            calibration_state: "uncalibrated",
          }),
        ],
      },
    ],
    coverage: [
      { stratum: "billing", sampled: 30, population: 300, coverage_fraction: 0.1 },
      { stratum: "returns", sampled: 5, population: null, coverage_fraction: null },
    ],
    missing_labels: { judged: 70, labelled: 50, missing: 20 },
    pilot_grounded_rate: pilot(),
    drift_alerts: [
      {
        dimension: "groundedness",
        subject_id: "commercial:contoso:foundry:agent_version:support-bot/v=3",
        detected_at: "2026-10-05T00:00:00Z",
        statistic: 0.31,
        threshold: 0.2,
      },
    ],
    ...over,
  };
}

function setup(path: string, opts: { body?: QualityResponse; status?: number }) {
  const fetchImpl = vi.fn<typeof fetch>(() =>
    Promise.resolve(
      opts.status !== undefined
        ? new Response(JSON.stringify({ status: opts.status }), { status: opts.status })
        : new Response(JSON.stringify(opts.body), { status: 200 }),
    ),
  );
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("t"),
    fetchImpl,
    maxRetries: 0,
  });
  const router = createMemoryRouter(qualityRoutes, { initialEntries: [path] });
  render(
    <QueryProvider client={client}>
      <RouterProvider router={router} />
    </QueryProvider>,
  );
  return { fetchImpl };
}

describe("quality page", () => {
  it("exports the route and nav item", () => {
    expect(qualityRoutes[0]?.path).toBe("quality");
    expect(qualityNavItems()).toEqual([{ to: "/quality", label: "Quality" }]);
  });

  it("asks for a domain and makes no request when none is selected", () => {
    const { fetchImpl } = setup("/quality", {});
    expect(screen.getByTestId("domain-required")).toBeTruthy();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("carries the domain only as a path segment", async () => {
    const { fetchImpl } = setup(PATH, { body: quality() });
    await screen.findByTestId("pilot-rate");
    const url = new URL(String(fetchImpl.mock.calls[0]?.[0]));
    expect(url.pathname).toBe(
      "/api/v1/evaluation/domains/commercial%3Acontoso%3Acatalog%3Adomain%3Afinance/quality",
    );
    expect(url.searchParams.has("domain_id")).toBe(false);
  });

  it("shows the pilot rate with interval, level, n and the exact target label", async () => {
    setup(PATH, { body: quality() });
    await screen.findByTestId("pilot-rate");
    expect(screen.getByTestId("pilot-target").textContent).toBe("pilot-set target: at least 90%");
    expect(screen.getByTestId("pilot-value").textContent).toBe("92%");
    expect(screen.getByTestId("pilot-interval").textContent).toBe("0.85 to 0.96 (95% level)");
    expect(screen.getByTestId("pilot-n").textContent).toBe("120");
  });

  it("shows a small-n wide interval as-is", async () => {
    setup(PATH, {
      body: quality({
        pilot_grounded_rate: pilot({ value: 1, lower: 0.439, upper: 1, n: 4 }),
      }),
    });
    await screen.findByTestId("pilot-rate");
    expect(screen.getByTestId("pilot-interval").textContent).toBe("0.439 to 1 (95% level)");
    expect(screen.getByTestId("pilot-n").textContent).toBe("4");
  });

  it("renders unknown, not 0, when the pilot rate is not estimable", async () => {
    setup(PATH, {
      body: quality({
        pilot_grounded_rate: pilot({
          value: null,
          lower: null,
          upper: null,
          level: null,
          n: 0,
          method: "not_estimable",
        }),
      }),
    });
    await screen.findByTestId("pilot-rate");
    expect(screen.getByTestId("pilot-value").textContent).toBe("unknown");
    expect(screen.getByTestId("pilot-reason").textContent).toContain("Not enough pilot data");
    expect(screen.getByTestId("pilot-target").textContent).toBe("pilot-set target: at least 90%");
    expect(screen.queryByTestId("pilot-interval")).toBeNull();
  });

  it("renders null metrics and coverage as unknown, never 0", async () => {
    setup(PATH, { body: quality() });
    await screen.findByTestId("pilot-rate");
    const safety = within(screen.getByTestId("trend-safety"));
    const row = safety.getByTestId("trend-row");
    expect(within(row).getByTestId("trend-value").textContent).toBe("unknown");
    expect(row.textContent).toContain("not estimable");
    const cov = screen.getAllByTestId("coverage-row")[1];
    expect(cov?.textContent).toContain("returns");
    expect(within(cov as HTMLElement).getByTestId("coverage-fraction").textContent).toBe("unknown");
    expect(cov?.textContent).toContain("unknown");
  });

  it("shows judge config and calibration state beside each score", async () => {
    setup(PATH, { body: quality() });
    await screen.findByTestId("pilot-rate");
    const grounded = within(screen.getByTestId("trend-groundedness"));
    const row = grounded.getByTestId("trend-row");
    expect(within(row).getByTestId("trend-judge").textContent).toContain("llm_judge");
    expect(row.textContent).toContain("judge-a 2026-08");
    expect(row.textContent).toContain("prompt p-3.1");
    expect(within(row).getByTestId("calibration-state").textContent).toBe("Calibrated");
    const safety = within(screen.getByTestId("trend-safety")).getByTestId("trend-row");
    expect(within(safety).getByTestId("calibration-state").textContent).toBe("Uncalibrated");
    expect(safety.textContent).toContain("Uncalibrated judge score");
  });

  it("shows missing-label counts and drift alerts", async () => {
    setup(PATH, { body: quality() });
    await screen.findByTestId("pilot-rate");
    expect(screen.getByTestId("missing-labels").textContent).toBe("20");
    expect(screen.getByTestId("label-row").textContent).toContain("70");
    expect(screen.getByTestId("drift-row").textContent).toContain("0.31");
  });

  it("renders unknown label counts as unknown, not 0", async () => {
    setup(PATH, {
      body: quality({ missing_labels: { judged: 70, labelled: null, missing: null } }),
    });
    await screen.findByTestId("pilot-rate");
    expect(screen.getByTestId("missing-labels").textContent).toBe("unknown");
  });

  it("never implies a guarantee, SLA or promise", async () => {
    const { fetchImpl } = setup(PATH, { body: quality() });
    await screen.findByTestId("pilot-rate");
    expect(fetchImpl).toHaveBeenCalled();
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/guarantee/i);
    expect(text).not.toMatch(/\bSLA\b/i);
    expect(text).not.toMatch(/ensures?/i);
    expect(text).not.toMatch(/promise/i);
  });

  it("has headings and table semantics", async () => {
    setup(PATH, { body: quality() });
    await screen.findByTestId("pilot-rate");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Agent quality");
    expect(screen.getAllByRole("heading", { level: 2 }).length).toBeGreaterThanOrEqual(5);
    expect(screen.getAllByRole("columnheader").length).toBeGreaterThan(0);
  });

  it("renders the forbidden state on 403", async () => {
    setup(PATH, { status: 403 });
    await screen.findByTestId("forbidden-state");
    expect(screen.getByText("You do not have access to this domain")).toBeTruthy();
    expect(screen.queryByTestId("pilot-rate")).toBeNull();
  });

  it("renders an unavailable state, not empty data, on 503", async () => {
    setup(PATH, { status: 503 });
    await screen.findByTestId("unavailable-state");
    expect(screen.getByText("Quality results are unavailable")).toBeTruthy();
    expect(screen.queryByTestId("pilot-rate")).toBeNull();
  });
});
