import { describe, expect, it, vi } from "vitest";
import { createApiClient } from "./client.js";
import {
  DependencyTransientError,
  ForbiddenError,
  RateLimitedError,
  ScopeParameterError,
  StaleVersionError,
  UnauthorizedError,
  UnexpectedResponseError,
} from "./errors.js";

type Call = { url: string; init: RequestInit };

function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function setup(responses: (Response | Error)[]) {
  const calls: Call[] = [];
  const queue = [...responses];
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init: init ?? {} });
    const next = queue.shift();
    if (next === undefined) throw new Error("no more responses");
    if (next instanceof Error) throw next;
    return next;
  }) as unknown as typeof fetch;
  const sleeps: number[] = [];
  let n = 0;
  const client = createApiClient({
    baseUrl: "https://api.example.test/",
    getToken: () => Promise.resolve("tok"),
    fetchImpl,
    sleep: (ms) => {
      sleeps.push(ms);
      return Promise.resolve();
    },
    newCorrelationId: () => `corr-${++n}`,
  });
  return { client, calls, sleeps };
}

const headersOf = (c: Call | undefined) => (c?.init.headers ?? {}) as Record<string, string>;
const problem = (code: string, status: number, extra: Record<string, unknown> = {}) => ({
  code,
  status,
  retryable: false,
  correlation_id: "srv",
  ...extra,
});

describe("request shape", () => {
  it("sends bearer token and a correlation id, builds the URL", async () => {
    const { client, calls } = setup([json(200, { ok: true })]);
    await expect(client.get("/v1/agents", { limit: 5, q: undefined })).resolves.toEqual({
      ok: true,
    });
    expect(calls[0]?.url).toBe("https://api.example.test/v1/agents?limit=5");
    expect(headersOf(calls[0])["Authorization"]).toBe("Bearer tok");
    expect(headersOf(calls[0])["x-correlation-id"]).toBe("corr-1");
  });

  it("uses a fresh correlation id per request via crypto.randomUUID by default", async () => {
    const calls: Call[] = [];
    const fetchImpl = (async (url: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(url), init: init ?? {} });
      return json(200, {});
    }) as typeof fetch;
    const client = createApiClient({
      baseUrl: "http://x",
      getToken: () => Promise.resolve("t"),
      fetchImpl,
    });
    await client.get("/a");
    await client.get("/a");
    const [a, b] = calls.map((c) => headersOf(c)["x-correlation-id"]);
    expect(a).toMatch(/^[0-9a-f-]{36}$/);
    expect(b).toMatch(/^[0-9a-f-]{36}$/);
    expect(a).not.toBe(b);
  });

  it("never adds domain_id or customer_id to the URL or body", async () => {
    const { client, calls } = setup([json(200, {})]);
    await client.post("/v1/queries", { name: "sample", filter: { kind: "agent" } });
    const call = calls[0];
    expect(call?.url).not.toMatch(/domain_id|customer_id/);
    expect(String(call?.init.body)).not.toMatch(/domain_id|customer_id/);
    expect(JSON.parse(String(call?.init.body))).toEqual({
      name: "sample",
      filter: { kind: "agent" },
    });
  });

  it("refuses caller-supplied scope in query or nested body, without calling fetch", async () => {
    const { client, calls } = setup([]);
    await expect(client.get("/x", { domain_id: "d" })).rejects.toBeInstanceOf(ScopeParameterError);
    await expect(client.post("/x", { a: [{ customer_id: "c" }] })).rejects.toBeInstanceOf(
      ScopeParameterError,
    );
    expect(calls).toHaveLength(0);
  });

  it("sends If-Match and returns undefined for 204", async () => {
    const { client, calls } = setup([new Response(null, { status: 204 })]);
    await expect(client.patch("/v1/agents/1", { n: 1 }, '"v3"')).resolves.toBeUndefined();
    expect(headersOf(calls[0])["If-Match"]).toBe('"v3"');
  });
});

describe("error mapping and retry", () => {
  it.each([
    [401, "unauthorized", UnauthorizedError],
    [403, "forbidden", ForbiddenError],
    [409, "stale_version", StaleVersionError],
  ] as const)("%i maps to %s and is not retried", async (status, code, cls) => {
    const { client, calls, sleeps } = setup([json(status, problem(code, status))]);
    const err = await client.get("/x").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(cls);
    expect(calls).toHaveLength(1);
    expect(sleeps).toHaveLength(0);
  });

  it("409 is never auto-retried even for a mutating or idempotent call", async () => {
    const { client, calls } = setup([
      json(409, problem("stale_version", 409, { retryable: true })),
    ]);
    await expect(client.put("/x", {}, '"v1"')).rejects.toBeInstanceOf(StaleVersionError);
    expect(calls).toHaveLength(1);
  });

  it("429 honors Retry-After then succeeds, reusing the correlation id", async () => {
    const { client, calls, sleeps } = setup([
      json(429, problem("rate_limited", 429, { retryable: true }), { "Retry-After": "3" }),
      json(200, { done: true }),
    ]);
    await expect(client.get("/x")).resolves.toEqual({ done: true });
    expect(sleeps).toEqual([3000]);
    expect(calls).toHaveLength(2);
    expect(headersOf(calls[1])["x-correlation-id"]).toBe(headersOf(calls[0])["x-correlation-id"]);
  });

  it("gives up after maxRetries on 429 and throws RateLimitedError", async () => {
    const r = () =>
      json(429, problem("rate_limited", 429, { retryable: true }), { "Retry-After": "1" });
    const { client, calls } = setup([r(), r(), r()]);
    await expect(client.get("/x")).rejects.toBeInstanceOf(RateLimitedError);
    expect(calls).toHaveLength(3);
  });

  it("503 policy outage is an error, never empty data, and retries only when retryable", async () => {
    const outage = problem("dependency_transient", 503, { retryable: false });
    const { client, calls } = setup([json(503, outage)]);
    const err = await client.get("/x").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(DependencyTransientError);
    expect(calls).toHaveLength(1);
  });

  it("retries a retryable 503 on GET but not on POST", async () => {
    const t = () => json(503, problem("dependency_transient", 503, { retryable: true }));
    const get = setup([t(), json(200, { a: 1 })]);
    await expect(get.client.get("/x")).resolves.toEqual({ a: 1 });
    const post = setup([t()]);
    await expect(post.client.post("/x", {})).rejects.toBeInstanceOf(DependencyTransientError);
    expect(post.calls).toHaveLength(1);
  });

  it("maps network failure to a retryable dependency_transient", async () => {
    const { client, calls } = setup([new TypeError("fetch failed"), json(200, { ok: 1 })]);
    await expect(client.get("/x")).resolves.toEqual({ ok: 1 });
    expect(calls).toHaveLength(2);
  });

  it("rejects an empty 200 rather than returning empty data", async () => {
    const { client } = setup([new Response("", { status: 200 })]);
    await expect(client.get("/x")).rejects.toBeInstanceOf(UnexpectedResponseError);
  });
});
