import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { QueryClient } from "@tanstack/react-query";
import { vi } from "vitest";
import { QueryProvider, createApiClient } from "../../../../api/index.js";
import { recommendationRoutes } from "../../routes";
import {
  SIGNAL_NAMES,
  type AgentMatchView,
  type MatchMetricsView,
  type SignalName,
} from "../types";

export class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

export const DOMAIN = "commercial:contoso:catalog:domain:finance";
export const WARM_ID = "commercial:contoso:sandbox:agent:invoice-summarizer";
export const COLD_ID = "commercial:contoso:sandbox:agent:ledger-helper";
export const TASK = "Summarize the quarterly invoice documents";
export const FIND_PATH = `/recommendations/find?domain_id=${encodeURIComponent(DOMAIN)}`;

function signals(unobserved: readonly SignalName[]) {
  return SIGNAL_NAMES.map((signal) => {
    const missing = unobserved.includes(signal);
    return {
      signal,
      value: missing ? null : 0.5,
      weight: 0.125,
      contribution: missing ? 0 : 0.0625,
    };
  });
}

export function view(over: Partial<AgentMatchView["match"]> = {}): AgentMatchView {
  return {
    match: {
      schema_version: "1.0.0",
      match_id: "m-1",
      domain_id: DOMAIN,
      generated_at: "2026-11-21T00:00:00Z",
      ranker: { ranker_id: "r", ranker_version: "1" },
      cold_start: false,
      signals_unavailable: [],
      truncated: false,
      partial_reason: null,
      candidates: [
        {
          rank: 1,
          entity_id: WARM_ID,
          entity_type: "agent",
          display_name: "Invoice Summarizer",
          lifecycle_status: "active",
          score: 0.71,
          signals: signals([]),
          matched_capabilities: ["document.summarize"],
          matched_tags: ["finance"],
          relations: [
            {
              relation_type: "uses_model",
              entity_id: "commercial:contoso:sandbox:model:gpt-e2e",
              direction: "outgoing",
            },
          ],
          evidence_ids: [],
        },
        {
          rank: 2,
          entity_id: COLD_ID,
          entity_type: "tool",
          display_name: "Ledger Helper",
          lifecycle_status: "active",
          score: 0.3,
          signals: signals(["historical_success", "latency", "usage"]),
          matched_capabilities: [],
          matched_tags: [],
          relations: [],
          evidence_ids: [],
        },
      ],
      ...over,
    },
    assessments: [
      { entity_id: WARM_ID, confidence: 0.86, cold_start: false },
      { entity_id: COLD_ID, confidence: 0.21, cold_start: true },
    ],
    confidence_note: "confidence is relative, not a probability",
  };
}

export function metrics(over: Partial<MatchMetricsView> = {}): MatchMetricsView {
  return {
    domain_id: DOMAIN,
    window_start: "2026-10-01T00:00:00Z",
    window_end: "2026-11-01T00:00:00Z",
    matches: 4,
    matches_with_feedback: 0,
    accepts: 0,
    rejects: 0,
    acceptance_rate: null,
    ...over,
  };
}

export interface Behaviour {
  match?: () => Response;
  feedback?: () => Response;
  metrics?: () => Response;
  completeness?: () => Response;
}

export const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status });

export function problem(status: number, code: string, reason: string): Response {
  return json({ code, reason, status, title: reason }, status);
}

export function makeClient(b: Behaviour) {
  const fetchImpl = vi.fn<typeof fetch>((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url.endsWith("/match/feedback") && method === "POST") {
      return Promise.resolve(
        b.feedback?.() ??
          json({ match_id: "m-1", entity_id: WARM_ID, decision: "accepted", decided_at: "x" }, 202),
      );
    }
    if (url.endsWith("/match/metrics")) return Promise.resolve(b.metrics?.() ?? json(metrics()));
    if (url.endsWith("/match") && method === "POST") {
      return Promise.resolve(b.match?.() ?? json(view()));
    }
    if (url.includes("/catalog/completeness")) {
      return Promise.resolve(b.completeness?.() ?? json({ detail: "nf" }, 404));
    }
    return Promise.resolve(json({ items: [] }));
  });
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("t"),
    fetchImpl,
    maxRetries: 0,
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return { fetchImpl, client, queryClient };
}

export function setupPage(b: Behaviour = {}, path: string = FIND_PATH) {
  const made = makeClient(b);
  const router = createMemoryRouter(recommendationRoutes, { initialEntries: [path] });
  const view_ = render(
    <QueryProvider client={made.client} queryClient={made.queryClient}>
      <RouterProvider router={router} />
    </QueryProvider>,
  );
  return { ...made, router, ...view_ };
}
