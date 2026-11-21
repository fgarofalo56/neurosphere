import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { QueryProvider } from "../../../../api/index.js";
import { MatchMetricsStrip } from "../MatchMetricsStrip";
import {
  DOMAIN,
  ResizeObserverStub,
  json,
  makeClient,
  metrics,
  problem,
  type Behaviour,
} from "./fixtures";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(cleanup);

function renderStrip(b: Behaviour) {
  const { client, queryClient } = makeClient(b);
  render(
    <QueryProvider client={client} queryClient={queryClient}>
      <MatchMetricsStrip domainId={DOMAIN} />
    </QueryProvider>,
  );
}

describe("MatchMetricsStrip", () => {
  it("shows 'No feedback yet' for a null rate, never 0%", async () => {
    renderStrip({});
    const rate = await screen.findByTestId("match-acceptance-rate");
    expect(rate).toHaveTextContent("No feedback yet");
    expect(rate).not.toHaveTextContent("0%");
    expect(screen.getByTestId("match-outcome-note")).toHaveTextContent(
      "an outcome to observe, not a target that has been met",
    );
  });

  it("shows counts and the rate as a percent", async () => {
    renderStrip({
      metrics: () =>
        json(
          metrics({
            matches: 5,
            accepts: 3,
            rejects: 1,
            matches_with_feedback: 4,
            acceptance_rate: 0.75,
          }),
        ),
    });
    expect(await screen.findByTestId("match-acceptance-rate")).toHaveTextContent("75%");
    expect(screen.getByTestId("match-metrics")).toHaveTextContent("Accepts");
    expect(screen.getByTestId("match-metrics")).toHaveTextContent("5");
  });

  it("shows the completeness tile as not available when the endpoint is absent", async () => {
    renderStrip({});
    await screen.findByTestId("match-acceptance-rate");
    expect(await screen.findByTestId("match-completeness")).toHaveTextContent("Not available");
  });

  it("treats a 503 capability_unavailable completeness body as absent", async () => {
    renderStrip({ completeness: () => problem(503, "capability_unavailable", "not_built") });
    await screen.findByTestId("match-acceptance-rate");
    expect(screen.getByTestId("match-completeness")).toHaveTextContent("Not available");
  });

  it("shows the completeness ratio when the endpoint answers", async () => {
    renderStrip({ completeness: () => json({ ratio: 0.8 }) });
    await screen.findByTestId("match-acceptance-rate");
    await vi.waitFor(() =>
      expect(screen.getByTestId("match-completeness")).toHaveTextContent("80%"),
    );
  });

  it("degrades when metrics fail without breaking the completeness tile", async () => {
    renderStrip({ metrics: () => problem(503, "dependency_transient", "down") });
    expect(await screen.findByTestId("match-metrics-unavailable")).toBeInTheDocument();
    expect(screen.getByTestId("match-completeness")).toBeInTheDocument();
  });
});
