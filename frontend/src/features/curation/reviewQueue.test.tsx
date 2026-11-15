import type { AccountInfo, IPublicClientApplication } from "@azure/msal-browser";
import { MsalProvider } from "@azure/msal-react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { QueryProvider, createApiClient } from "../../api/index.js";
import { DomainProvider } from "../../app/domain";
import { createStubMsalInstance } from "../../../tests/e2e-support/stubMsal";
import { reviewQueuePath, reviewResolvePath } from "./paths";
import { ReviewQueuePage, ageLabel } from "./ReviewQueuePage";
import type { ReviewItemView } from "./types";

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(cleanup);

const DOMAIN = "commercial:test:catalog:domain:finance";
const ITEM: ReviewItemView = {
  id: "review:abc/def",
  edge_id: "commercial:test:catalog:uses_model:agent-a/model-b",
  relation_type: "uses_model",
  domain_id: DOMAIN,
  reason: "conflicts_with_lock",
  observed_confidence: 0.4,
  presented_confidence: 0.9,
  created_at: "2026-10-01T08:00:00Z",
  status: "open",
};

function account(): AccountInfo {
  return {
    homeAccountId: "home-rq",
    environment: "login.example.invalid",
    tenantId: "test-tenant",
    username: "someone@example.invalid",
    localAccountId: "local",
    name: "Test User",
    idTokenClaims: { roles: ["Steward"] },
  };
}

function msal(): IPublicClientApplication {
  const base = createStubMsalInstance() as unknown as Record<string, unknown>;
  const acc = account();
  return {
    ...base,
    getAllAccounts: () => [acc],
    getActiveAccount: () => acc,
  } as unknown as IPublicClientApplication;
}

function json(body: unknown, status = 200): Response {
  const type = status >= 400 ? "application/problem+json" : "application/json";
  return new Response(JSON.stringify(body), { status, headers: { "content-type": type } });
}

function problem(status: number, code: string): Response {
  return json(
    {
      type: "about:blank",
      title: code,
      status,
      detail: code,
      instance: "/x",
      code,
      retryable: false,
      correlation_id: "corr-test",
    },
    status,
  );
}

interface Call {
  readonly method: string;
  readonly path: string;
  readonly body: unknown;
}

function mount(handlers: {
  readonly list: () => Response;
  readonly resolve?: () => Response;
}): Call[] {
  const calls: Call[] = [];
  const fetchImpl: typeof fetch = (input, init) => {
    const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw);
    const method = init?.method ?? "GET";
    const body = typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined;
    calls.push({ method, path: url.pathname, body });
    if (url.pathname === "/api/v1/me/domains") {
      return Promise.resolve(
        json({
          items: [
            {
              domain_id: DOMAIN,
              display_name: "Finance",
              display_name_source: "catalog",
              cloud: "commercial",
              permissions: ["data.read", "catalog.curate"],
            },
          ],
        }),
      );
    }
    if (method === "GET" && url.pathname === reviewQueuePath()) {
      return Promise.resolve(handlers.list());
    }
    if (method === "POST" && url.pathname === reviewResolvePath(ITEM.id)) {
      return Promise.resolve(handlers.resolve?.() ?? json({ ...ITEM, status: "resolved" }));
    }
    return Promise.reject(new Error(`unhandled request: ${method} ${url.pathname}`));
  };
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("test-credential"),
    fetchImpl,
    maxRetries: 0,
  });
  render(
    <MsalProvider instance={msal()}>
      <QueryProvider client={client}>
        <MemoryRouter initialEntries={["/catalog/review-queue"]}>
          <DomainProvider>
            <ReviewQueuePage />
          </DomainProvider>
        </MemoryRouter>
      </QueryProvider>
    </MsalProvider>,
  );
  return calls;
}

describe("ageLabel", () => {
  it("formats minutes, hours and days", () => {
    const now = Date.parse("2026-10-10T12:00:00Z");
    expect(ageLabel("2026-10-10T11:30:00Z", now)).toBe("30 min");
    expect(ageLabel("2026-10-10T07:00:00Z", now)).toBe("5 h");
    expect(ageLabel("2026-10-05T12:00:00Z", now)).toBe("5 d");
  });
});

describe("review queue page", () => {
  it("lists an open item with an edge link and its age", async () => {
    mount({ list: () => json({ items: [ITEM] }) });
    const row = await screen.findByTestId("review-row");
    const link = row.querySelector("a");
    expect(link?.getAttribute("href")).toBe(
      `/catalog/edge?edge_id=${encodeURIComponent(ITEM.edge_id)}`,
    );
    expect(row.querySelector("time")?.getAttribute("datetime")).toBe(ITEM.created_at);
    expect(row).toHaveTextContent("Inference conflicts with a lock");
  });

  it("shows the empty state", async () => {
    mount({ list: () => json({ items: [] }) });
    expect(await screen.findByTestId("empty-state")).toBeInTheDocument();
  });

  it("shows the forbidden state on 403", async () => {
    mount({ list: () => problem(403, "forbidden") });
    expect(await screen.findByTestId("forbidden-state")).toBeInTheDocument();
  });

  it("shows a retryable error on 503", async () => {
    mount({ list: () => problem(503, "dependency_transient") });
    expect(await screen.findByTestId("query-error")).toBeInTheDocument();
  });

  it("resolves through the dialog and sends only the outcome", async () => {
    const calls = mount({ list: () => json({ items: [ITEM] }) });
    fireEvent.click(await screen.findByTestId("resolve-open"));
    await screen.findByTestId("change-confirm-dialog");
    // code mode: no free-text reason field, submit is enabled straight away
    expect(screen.queryByRole("textbox", { hidden: true })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Confirm change", hidden: true }));
    await waitFor(() => expect(screen.getByTestId("resolve-done")).toBeInTheDocument());
    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe(reviewResolvePath(ITEM.id));
    expect(post?.body).toEqual({ resolution: "kept_curation" });
  });
});
