import { cleanup, render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { QueryProvider, createApiClient } from "../../../api/index.js";
import { reviewRoutes } from "../index";
import type { CalibrationSampleView, ReviewItemView } from "../types";

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});

afterEach(cleanup);

const DOMAIN = "commercial:contoso:catalog:domain:finance";
const ITEMS = `/api/v1/review/domains/${encodeURIComponent(DOMAIN)}/items`;
const SAMPLES = `/api/v1/evaluation/domains/${encodeURIComponent(DOMAIN)}/calibration-samples`;
const ITEM_ID = "44444444-4444-4444-8444-444444444444";
const SUBJECT = `commercial:contoso:evaluation:dispute:${"a".repeat(40)}`;
const ITEM_PATH = `/review/item?domain_id=${encodeURIComponent(DOMAIN)}&item_id=${ITEM_ID}`;

function item(over: Partial<ReviewItemView> = {}): ReviewItemView {
  return {
    item_id: ITEM_ID,
    kind: "evaluation_dispute",
    state: "pending",
    domain_id: DOMAIN,
    subject_ref: SUBJECT,
    intent_id: null,
    assignee_pseudonym: null,
    sla_due_at: "2099-01-01T00:00:00Z",
    escalation_level: 0,
    created_at: "2026-10-20T10:00:00Z",
    decisions: [],
    effective_decision_id: null,
    superseded_decision_ids: [],
    ...over,
  };
}

function sample(over: Partial<CalibrationSampleView> = {}): CalibrationSampleView {
  return {
    subject_ref: SUBJECT,
    domain_id: DOMAIN,
    dataset_id: "ds-pilot",
    dataset_version: "3",
    item_id: "item-0007",
    dimension: "groundedness",
    classification: "internal",
    judge_config_id: "judge-a",
    judge_config_version: "7",
    value: 1,
    rubric_id: "rubric-t",
    rubric_version: "2",
    opened_at: "2026-10-20T09:00:00Z",
    payload: { question: "What is the refund limit?", answer: "500 USD" },
    payload_withheld: false,
    withheld_reason: null,
    ...over,
  };
}

interface Reply {
  status: number;
  body: unknown;
}

function setup(routes: Record<string, Reply>) {
  const calls: { path: string; search: string }[] = [];
  const fetchImpl = vi.fn<typeof fetch>((input, init) => {
    const url = new URL(String(input));
    calls.push({ path: url.pathname, search: url.search });
    const route = routes[`${init?.method ?? "GET"} ${url.pathname}`];
    if (route === undefined) {
      return Promise.resolve(new Response(JSON.stringify({ status: 404 }), { status: 404 }));
    }
    return Promise.resolve(new Response(JSON.stringify(route.body), { status: route.status }));
  });
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("t"),
    fetchImpl,
    maxRetries: 0,
  });
  const router = createMemoryRouter(reviewRoutes, { initialEntries: [ITEM_PATH] });
  render(
    <QueryProvider client={client}>
      <RouterProvider router={router} />
    </QueryProvider>,
  );
  return { calls };
}

describe("evaluation dispute context", () => {
  it("shows the dataset item, the verdict in words, versions and the approve/reject meaning", async () => {
    const { calls } = setup({
      [`GET ${ITEMS}/${ITEM_ID}`]: { status: 200, body: item() },
      [`GET ${SAMPLES}`]: { status: 200, body: sample() },
    });
    const region = await screen.findByRole("region", { name: "Judge verdict under review" });
    await within(region).findByTestId("dispute-item");
    expect(within(region).getByTestId("dispute-instruction").textContent).toBe(
      "Approve if the judge was wrong. Reject if the judge was right.",
    );
    expect(within(region).getByTestId("dispute-item").textContent).toBe("item-0007");
    expect(within(region).getByTestId("dispute-dimension").textContent).toBe("groundedness");
    expect(within(region).getByTestId("dispute-verdict").textContent).toBe("Pass (1)");
    expect(within(region).getByTestId("dispute-judge").textContent).toBe("judge-a 7");
    expect(within(region).getByTestId("dispute-rubric").textContent).toBe("rubric-t 2");
    expect(within(region).getByTestId("dispute-classification").textContent).toBe("internal");
    expect(within(region).getByTestId("dispute-dataset").textContent).toBe("ds-pilot 3");
    expect(within(region).getByTestId("dispute-payload").textContent).toContain("refund limit");
    const call = calls.find((c) => c.path === SAMPLES);
    expect(new URLSearchParams(call?.search).get("subject_ref")).toBe(SUBJECT);
    expect(new URLSearchParams(call?.search).has("domain_id")).toBe(false);
  });

  it("spells a failing verdict as Fail", async () => {
    setup({
      [`GET ${ITEMS}/${ITEM_ID}`]: { status: 200, body: item() },
      [`GET ${SAMPLES}`]: { status: 200, body: sample({ value: 0 }) },
    });
    expect((await screen.findByTestId("dispute-verdict")).textContent).toBe("Fail (0)");
  });

  it("says the content is withheld for a restricted item and shows no payload", async () => {
    setup({
      [`GET ${ITEMS}/${ITEM_ID}`]: { status: 200, body: item() },
      [`GET ${SAMPLES}`]: {
        status: 200,
        body: sample({
          classification: null,
          payload: null,
          payload_withheld: true,
          withheld_reason: "restricted",
        }),
      },
    });
    expect((await screen.findByTestId("dispute-withheld")).textContent).toBe(
      "Content withheld (restricted)",
    );
    expect(screen.queryByTestId("dispute-payload")).toBeNull();
    expect(screen.getByTestId("dispute-classification").textContent).toBe("unknown");
  });

  it("shows a loading state while the sample is fetched", async () => {
    const fetchImpl = vi.fn<typeof fetch>((input) =>
      String(input).includes("calibration-samples")
        ? new Promise<Response>(() => undefined)
        : Promise.resolve(new Response(JSON.stringify(item()), { status: 200 })),
    );
    const client = createApiClient({
      baseUrl: "http://api.test",
      getToken: () => Promise.resolve("t"),
      fetchImpl,
      maxRetries: 0,
    });
    render(
      <QueryProvider client={client}>
        <RouterProvider
          router={createMemoryRouter(reviewRoutes, { initialEntries: [ITEM_PATH] })}
        />
      </QueryProvider>,
    );
    const loading = await screen.findByTestId("dispute-loading");
    expect(loading.getAttribute("aria-busy")).toBe("true");
  });

  it("explains a 404 in plain text, without an empty state", async () => {
    setup({
      [`GET ${ITEMS}/${ITEM_ID}`]: { status: 200, body: item() },
      [`GET ${SAMPLES}`]: { status: 404, body: { status: 404, title: "Not Found" } },
    });
    expect((await screen.findByTestId("dispute-none")).textContent).toBe(
      "No calibration context recorded for this item",
    );
    expect(screen.queryByTestId("empty-state")).toBeNull();
    // The decision controls are still there: the reviewer is not blocked by missing context.
    expect(screen.getByRole("button", { name: "Approve" })).toBeTruthy();
  });

  it("shows a retryable error on a server failure", async () => {
    setup({
      [`GET ${ITEMS}/${ITEM_ID}`]: { status: 200, body: item() },
      [`GET ${SAMPLES}`]: {
        status: 503,
        body: {
          type: "about:blank",
          title: "x",
          status: 503,
          code: "dependency_transient",
          retryable: true,
          correlation_id: "corr-1",
        },
      },
    });
    const region = await screen.findByRole("region", { name: "Judge verdict under review" });
    const state = await within(region).findByTestId("unavailable-state");
    expect(within(state).getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("renders nothing about calibration for other review kinds", async () => {
    const { calls } = setup({
      [`GET ${ITEMS}/${ITEM_ID}`]: {
        status: 200,
        body: item({ kind: "relationship", subject_ref: "commercial:contoso:catalog:agent:a" }),
      },
    });
    await screen.findByTestId("review-item");
    expect(screen.queryByTestId("calibration-context")).toBeNull();
    expect(screen.queryByText(/Approve if the judge was wrong/)).toBeNull();
    expect(calls.some((c) => c.path === SAMPLES)).toBe(false);
  });
});
