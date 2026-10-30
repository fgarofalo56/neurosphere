import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { QueryProvider, createApiClient } from "../../api/index.js";
import { EvaluationsPage } from "./EvaluationsPage";
import { evaluationResultsPath } from "./paths";
import { STRINGS } from "./strings";

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(cleanup);

const API = "http://api.test";
const DOMAIN = "commercial:test:catalog:domain:finance";
const SUBJECT = "commercial:test:catalog:model_deployment:m1";

let activeFetch: typeof fetch = () => Promise.reject(new Error("useApi() was not called"));

function json(body: unknown, status = 200, type = "application/json"): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": type } });
}

function result(id: string, over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    evaluation_id: id,
    subject_id: SUBJECT,
    mode: "offline_benchmark",
    status: "completed",
    judge: {
      judge_kind: "llm_judge",
      judge_model_id: "commercial:test:catalog:model_deployment:judge",
      judge_model_version: "v3",
      judge_prompt_version: "p2",
    },
    scores: [
      {
        dimension: "groundedness",
        value: 0.8125,
        scale: { min: 0, max: 1 },
        uncertainty: { method: "bootstrap", lower: 0.7421875, upper: 0.8828125, level: 0.95 },
        sample_size: 41,
      },
    ],
    calibration: {
      calibration_ref: "cal-1",
      human_label_set_version: "labels-1",
      agreement: { metric: "cohen_kappa", value: 0.71, sample_size: 120 },
      calibrated_at: "2026-10-01T00:00:00.000000Z",
    },
    completed_at: "2026-10-20T10:00:00.000000Z",
    ...over,
  };
}

/** Strict fake API: an unmatched request rejects, so the page cannot call anything unplanned. */
function useApi(handler: (url: URL) => Response): URL[] {
  const urls: URL[] = [];
  activeFetch = (input) => {
    const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw);
    urls.push(url);
    return url.pathname === evaluationResultsPath(DOMAIN)
      ? Promise.resolve(handler(url))
      : Promise.reject(new Error(`unhandled request: ${url.pathname}`));
  };
  return urls;
}

function renderPage() {
  const client = createApiClient({
    baseUrl: API,
    getToken: () => Promise.resolve("test-credential"),
    fetchImpl: (input, init) => activeFetch(input, init),
    maxRetries: 0,
  });
  return render(
    <QueryProvider client={client}>
      <MemoryRouter initialEntries={[`/evaluations?domain_id=${encodeURIComponent(DOMAIN)}`]}>
        <EvaluationsPage />
      </MemoryRouter>
    </QueryProvider>,
  );
}

describe("EvaluationsPage", () => {
  it("shows score, judge, calibration and uncertainty exactly as returned", async () => {
    const urls = useApi(() => json({ items: [result("e1")], next_cursor: null }));
    renderPage();
    const row = await screen.findByTestId("evaluation-row");
    expect(within(row).getByText("groundedness")).toBeTruthy();
    expect(within(row).getByText(STRINGS.scoreText(0.8125, 0, 1))).toBeTruthy();
    expect(
      within(row).getByText(/llm_judge: commercial:test:catalog:model_deployment:judge v3 p2/),
    ).toBeTruthy();
    expect(within(row).getByText(/cohen_kappa 0.71 \(n=120\)/)).toBeTruthy();
    expect(within(row).getByText("bootstrap, 0.7421875 to 0.8828125, level 0.95")).toBeTruthy();
    expect(screen.getByTestId("evaluations-count").textContent).toBe(STRINGS.endNote(1));
    const quality = screen.getByTestId("evaluations-quality-link");
    expect(quality.getAttribute("href")).toContain("/quality?domain_id=");
    expect(urls).toHaveLength(1);
    expect(urls[0]?.searchParams.has("domain_id")).toBe(false);
    expect(urls[0]?.searchParams.has("customer_id")).toBe(false);
  });

  it("never turns a null score or missing calibration into a number", async () => {
    useApi(() =>
      json({
        items: [
          result("e1", {
            judge: { judge_kind: "programmatic", program_version: "rules-1" },
            calibration: null,
            scores: [
              {
                dimension: "safety",
                value: null,
                scale: { min: 0, max: 1 },
                uncertainty: { method: "not_estimable" },
                sample_size: 0,
              },
            ],
          }),
        ],
        next_cursor: null,
      }),
    );
    renderPage();
    const row = await screen.findByTestId("evaluation-row");
    expect(within(row).getByText(STRINGS.notScored)).toBeTruthy();
    expect(within(row).getByText(STRINGS.noCalibration)).toBeTruthy();
    expect(within(row).getByText(STRINGS.uncertaintyNotEstimable)).toBeTruthy();
    expect(within(row).getByText("programmatic: rules-1")).toBeTruthy();
  });

  it("sends subject and dimension filters and pages by the server cursor", async () => {
    const urls = useApi((url) =>
      url.searchParams.get("cursor") === null
        ? json({ items: [result("e1")], next_cursor: "c2" })
        : json({ items: [result("e2")], next_cursor: null }),
    );
    renderPage();
    await screen.findByTestId("evaluations-more");
    expect(screen.getByTestId("evaluations-count").textContent).toBe(STRINGS.moreNote(1));
    fireEvent.click(screen.getByTestId("evaluations-more"));
    await waitFor(() => expect(screen.getAllByTestId("evaluation-row")).toHaveLength(2));
    expect(urls.at(-1)?.searchParams.get("cursor")).toBe("c2");
    expect(screen.queryByTestId("evaluations-more")).toBeNull();

    fireEvent.change(screen.getByLabelText(STRINGS.subjectLabel), { target: { value: SUBJECT } });
    fireEvent.click(screen.getByTestId("evaluations-apply"));
    await waitFor(() => expect(urls.at(-1)?.searchParams.get("subject_id")).toBe(SUBJECT));
  });

  it("shows an empty state and an access-denied state distinctly", async () => {
    useApi(() => json({ items: [], next_cursor: null }));
    renderPage();
    await screen.findByTestId("evaluations-empty");
    cleanup();
    useApi(() =>
      json(
        {
          schema_version: "1.0.0",
          type: "https://neurosphere.invalid/problems/forbidden",
          title: "Forbidden",
          status: 403,
          detail: "domain_out_of_scope",
          instance: "/x",
          code: "forbidden",
          reason: "domain_out_of_scope",
          retryable: false,
          correlation_id: "corr-1",
        },
        403,
        "application/problem+json",
      ),
    );
    renderPage();
    await screen.findByTestId("forbidden-state");
    expect(screen.queryByTestId("evaluations-empty")).toBeNull();
  });
});
