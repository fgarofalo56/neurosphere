import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { vi } from "vitest";
import { QueryProvider, createApiClient } from "../../../api/index.js";
import { recommendationRoutes } from "../routes";
import type {
  Recommendation,
  RecommendationDetailResponse,
  RecommendationListResponse,
} from "../types";

// jsdom has no ResizeObserver, which Fluent MessageBar uses.
export class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

export const DOMAIN = "commercial:contoso:catalog:domain:finance";
export const REC_ID = "commercial:contoso:neurosphere:recommendation:rec-0003";

/** Mirrors packages/contracts/schemas/recommendations/v1/examples/valid/model-right-sizing. */
export function rec(over: Partial<Recommendation> = {}): Recommendation {
  return {
    schema_version: "1.0.0",
    recommendation_id: REC_ID,
    cloud: "commercial",
    customer_id: "contoso",
    domain_id: DOMAIN,
    kind: "model_right_sizing",
    subject_ids: [
      "commercial:contoso:foundry:agent_version:support-bot/v=3",
      "commercial:contoso:foundry:model_deployment:gpt-large-eastus",
    ],
    method: "statistical",
    generator: { generator_id: "rule.right-sizing", generator_version: "1.2.0" },
    evidence_status: "sufficient",
    score: 0.64,
    evidence_window: { start: "2026-09-10T00:00:00Z", end: "2026-10-10T00:00:00Z" },
    evidence_ids: ["ev:eval:offline-42"],
    coverage: { method: "sampled", observed_fraction: 0.2, sampling_rate: 0.2 },
    uncertainty: { method: "confidence_interval", lower: 0.51, upper: 0.74, level: 0.9 },
    prerequisites: [
      { kind: "quality_regression_test", status: "unmet" },
      { kind: "tool_compatibility", status: "met", evidence_ids: ["ev:compat:7"] },
    ],
    projected_estimate: {
      estimate_kind: "estimated",
      period: "monthly",
      baseline_amount: "1840.00",
      projected_amount: "1210.50",
      lower_amount: "1105.00",
      upper_amount: "1390.00",
      currency: "USD",
      price_version: "azure-retail-2026-10-01",
      price_effective_date: "2026-10-01",
    },
    owner: { resolution: "inferred", owner_id: "commercial:contoso:entra:owner:team-support" },
    advisory: false,
    created_at: "2026-10-10T06:00:00Z",
    ...over,
  };
}

/** Cold start: no score, unestimable uncertainty, unknown coverage, unresolved owner, no estimate. */
export function coldStartRec(): Recommendation {
  const base = rec();
  delete base.score;
  delete base.projected_estimate;
  delete base.generator;
  return {
    ...base,
    kind: "unused_agent",
    method: "rule",
    evidence_status: "insufficient_evidence",
    evidence_ids: [],
    coverage: { method: "unknown", observed_fraction: null },
    uncertainty: { method: "not_estimable" },
    prerequisites: [],
    owner: { resolution: "unresolved", owner_id: null },
  };
}

export function detail(
  recommendation: Recommendation = rec(),
  over: Partial<RecommendationDetailResponse> = {},
): RecommendationDetailResponse {
  return {
    recommendation,
    review: { state: "not_routed", review_request_id: null },
    execution: { executable: false, reason: "action gates not passed" },
    ...over,
  };
}

export const REVIEW_ID = "rev-0001";

export interface Handlers {
  list?: RecommendationListResponse;
  detail?: RecommendationDetailResponse;
  /** Force this status on every GET. */
  status?: number;
  /** Force this status on the review POST. */
  reviewStatus?: number;
}

export function setupPage(path: string, handlers: Handlers) {
  const fetchImpl = vi.fn<typeof fetch>((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (method === "POST") {
      if (handlers.reviewStatus !== undefined) {
        return Promise.resolve(
          new Response(JSON.stringify({ status: handlers.reviewStatus }), {
            status: handlers.reviewStatus,
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ review_request_id: REVIEW_ID, state: "pending_review" }), {
          status: 202,
        }),
      );
    }
    if (handlers.status !== undefined) {
      return Promise.resolve(
        new Response(JSON.stringify({ status: handlers.status }), { status: handlers.status }),
      );
    }
    const isDetail = url.includes("/items/");
    const body = isDetail ? handlers.detail : handlers.list;
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
  });
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("t"),
    fetchImpl,
    maxRetries: 0,
  });
  const router = createMemoryRouter(recommendationRoutes, { initialEntries: [path] });
  const view = render(
    <QueryProvider client={client}>
      <RouterProvider router={router} />
    </QueryProvider>,
  );
  return { fetchImpl, ...view };
}

export const detailPath = (): string =>
  `/recommendations/detail?domain_id=${encodeURIComponent(DOMAIN)}&recommendation_id=${encodeURIComponent(REC_ID)}`;
export const listPath = (): string => `/recommendations?domain_id=${encodeURIComponent(DOMAIN)}`;
