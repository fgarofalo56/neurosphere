import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";
import { QueryProvider, createApiClient } from "../../../api/index.js";
import { AdminTransportProvider } from "./transport";

/** What a fake endpoint answers. `body` is JSON-encoded unless `raw` is set. */
export interface FakeReply {
  readonly status?: number;
  readonly body?: unknown;
  readonly raw?: string;
  readonly headers?: Record<string, string>;
}

export interface FakeRequest {
  readonly method: string;
  readonly url: URL;
  readonly headers: Headers;
  readonly body: unknown;
}

export type FakeHandler = (req: FakeRequest) => FakeReply | undefined;

/** A fetch that records every call and answers through `handler` (404 when it returns nothing). */
export function fakeFetch(handler: FakeHandler) {
  const calls: FakeRequest[] = [];
  const impl = vi.fn<typeof fetch>((input, init) => {
    const headers = new Headers(init?.headers);
    const raw = typeof init?.body === "string" ? init.body : undefined;
    const req: FakeRequest = {
      method: init?.method ?? "GET",
      url: new URL(String(input)),
      headers,
      body: raw === undefined ? undefined : (JSON.parse(raw) as unknown),
    };
    calls.push(req);
    const reply = handler(req) ?? { status: 404, body: { detail: "not found" } };
    const status = reply.status ?? 200;
    const isProblem = status >= 400;
    return Promise.resolve(
      new Response(reply.raw ?? JSON.stringify(reply.body ?? {}), {
        status,
        headers: {
          "content-type": isProblem ? "application/problem+json" : "application/json",
          ...reply.headers,
        },
      }),
    );
  });
  return { impl, calls };
}

export function problem(status: number, code: string, detail: string): FakeReply {
  return {
    status,
    body: {
      schema_version: "1.0.0",
      type: `https://neurosphere.invalid/problems/${code}`,
      title: detail,
      status,
      detail,
      instance: "/",
      code,
      reason: detail,
      retryable: false,
      correlation_id: "corr-test",
    },
  };
}

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

/** jsdom has no ResizeObserver, which Fluent MessageBar uses. Call from `beforeAll`. */
export function stubResizeObserver(): void {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
}

/** Renders a page with the API client, admin transport and a router, all over one fake fetch. */
export function renderAdmin(ui: ReactElement, fetchImpl: typeof fetch, initialEntry = "/") {
  const getToken = (): Promise<string> => Promise.resolve("test-token");
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken,
    fetchImpl,
    maxRetries: 0,
  });
  return render(
    <QueryProvider client={client}>
      <AdminTransportProvider transport={{ baseUrl: "http://api.test", getToken, fetchImpl }}>
        <MemoryRouter initialEntries={[initialEntry]}>{ui}</MemoryRouter>
      </AdminTransportProvider>
    </QueryProvider>,
  );
}
