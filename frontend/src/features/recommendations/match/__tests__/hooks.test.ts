import { QueryClient } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { QueryProvider, ScopeParameterError, createApiClient } from "../../../../api/index.js";
import {
  matchFeedbackPath,
  matchMetricsPath,
  matchPath,
  useAgentMatch,
  useMatchCompleteness,
  useMatchFeedback,
  useMatchMetrics,
} from "../hooks";
import { joinAssessments, type AgentMatchView, type MatchMetricsView } from "../types";

const DOMAIN = "commercial:contoso:catalog:domain:finance";
const ENC = "commercial%3Acontoso%3Acatalog%3Adomain%3Afinance";

type Responder = (url: URL, init: RequestInit | undefined) => Response;

function setup(responder: Responder) {
  const fetchImpl = vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
    Promise.resolve(responder(new URL(String(input)), init)),
  );
  const client = createApiClient({
    baseUrl: "http://x",
    getToken: () => Promise.resolve("t"),
    fetchImpl: fetchImpl as unknown as typeof fetch,
    maxRetries: 0,
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryProvider, { client, queryClient, children });
  return { fetchImpl, wrapper, queryClient };
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

const metrics = (accepts: number): MatchMetricsView => ({
  domain_id: DOMAIN,
  window_start: "2026-10-01T00:00:00Z",
  window_end: "2026-11-01T00:00:00Z",
  matches: 3,
  matches_with_feedback: accepts,
  accepts,
  rejects: 0,
  acceptance_rate: accepts === 0 ? null : 1,
});

describe("path building", () => {
  it("encodes the domain as a single path segment", () => {
    expect(matchPath(DOMAIN)).toBe(`/api/v1/recommendations/domains/${ENC}/match`);
    expect(matchFeedbackPath(DOMAIN)).toBe(`/api/v1/recommendations/domains/${ENC}/match/feedback`);
    expect(matchMetricsPath(DOMAIN)).toBe(`/api/v1/recommendations/domains/${ENC}/match/metrics`);
    expect(matchPath("a/b")).toContain("/domains/a%2Fb/match");
  });
});

describe("useAgentMatch", () => {
  it("POSTs the request to the encoded match path", async () => {
    const { fetchImpl, wrapper } = setup(() => json({ match: {}, assessments: [] }));
    const { result } = renderHook(() => useAgentMatch(), { wrapper });
    const request = { schema_version: "1.0.0", task_text: "summarize invoices" };
    result.current.mutate({ domainId: DOMAIN, request });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(new URL(url).pathname).toBe(`/api/v1/recommendations/domains/${ENC}/match`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual(request);
  });

  it("refuses a scope claim in the body before any request is sent", async () => {
    const { fetchImpl, wrapper } = setup(() => json({}));
    const { result } = renderHook(() => useAgentMatch(), { wrapper });
    const request = { schema_version: "1.0.0", task_text: "x", domain_id: "evil" };
    result.current.mutate({ domainId: DOMAIN, request });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(ScopeParameterError);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe("useMatchFeedback and useMatchMetrics", () => {
  it("refetches metrics after a successful feedback", async () => {
    let accepts = 0;
    const { fetchImpl, wrapper } = setup((url, init) => {
      if (init?.method === "POST") {
        accepts = 1;
        return json(
          { match_id: "m1", entity_id: "e1", decision: "accepted", decided_at: "t" },
          202,
        );
      }
      expect(url.pathname).toBe(`/api/v1/recommendations/domains/${ENC}/match/metrics`);
      return json(metrics(accepts));
    });
    const { result } = renderHook(
      () => ({ metrics: useMatchMetrics({ domainId: DOMAIN }), feedback: useMatchFeedback() }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.metrics.data?.accepts).toBe(0));
    result.current.feedback.mutate({
      domainId: DOMAIN,
      request: { schema_version: "1.0.0", match_id: "m1", entity_id: "e1", decision: "accepted" },
    });
    await waitFor(() => expect(result.current.metrics.data?.accepts).toBe(1));
    const post = fetchImpl.mock.calls.find(([, i]) => i?.method === "POST");
    expect(new URL(String(post?.[0])).pathname).toBe(
      `/api/v1/recommendations/domains/${ENC}/match/feedback`,
    );
  });

  it("refuses a scope claim in the feedback body", async () => {
    const { fetchImpl, wrapper } = setup(() => json({}, 202));
    const { result } = renderHook(() => useMatchFeedback(), { wrapper });
    result.current.mutate({
      domainId: DOMAIN,
      request: {
        schema_version: "1.0.0",
        match_id: "m1",
        entity_id: "e1",
        decision: "rejected",
        customer_id: "evil",
      } as never,
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(ScopeParameterError);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe("useMatchCompleteness", () => {
  it("is absent on HTTP 404", async () => {
    const { wrapper } = setup(() => json({ detail: "not found" }, 404));
    const { result } = renderHook(() => useMatchCompleteness({}), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual({ state: "absent" }));
  });

  it("is absent on a capability_unavailable body", async () => {
    const { wrapper } = setup(() =>
      json({ code: "capability_unavailable", reason: "capability_unavailable", status: 400 }, 400),
    );
    const { result } = renderHook(() => useMatchCompleteness({}), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual({ state: "absent" }));
  });

  it("is absent on a 503 whose problem body says capability_unavailable", async () => {
    const { wrapper } = setup(() =>
      json({ code: "capability_unavailable", reason: "capability_unavailable", status: 503 }, 503),
    );
    const { result } = renderHook(() => useMatchCompleteness({}), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual({ state: "absent" }));
  });

  it("stays an error on a plain 503", async () => {
    const { wrapper } = setup(() => json({ status: 503 }, 503));
    const { result } = renderHook(() => useMatchCompleteness({}), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });

  it("is present on 200", async () => {
    const { wrapper } = setup(() => json({ ratio: 0.5 }));
    const { result } = renderHook(() => useMatchCompleteness({}), { wrapper });
    await waitFor(() =>
      expect(result.current.data).toEqual({ state: "present", data: { ratio: 0.5 } }),
    );
  });

  it("keeps a non-404 error as an error", async () => {
    const { wrapper } = setup(() => json({ code: "forbidden", status: 403 }, 403));
    const { result } = renderHook(() => useMatchCompleteness({}), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
    expect(result.current.error?.code).toBe("forbidden");
  });
});

describe("joinAssessments", () => {
  it("pairs by entity_id and leaves a missing assessment undefined", () => {
    const cand = (id: string) => ({ entity_id: id }) as never;
    const view = {
      match: { candidates: [cand("a"), cand("b")] },
      assessments: [{ entity_id: "b", confidence: 0.4, cold_start: true }],
      confidence_note: "n",
    } as unknown as AgentMatchView;
    const joined = joinAssessments(view);
    expect(joined[0]?.assessment).toBeUndefined();
    expect(joined[1]?.assessment).toEqual({ entity_id: "b", confidence: 0.4, cold_start: true });
  });
});
