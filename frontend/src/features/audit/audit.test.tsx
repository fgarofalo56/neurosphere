import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { QueryProvider, createApiClient } from "../../api/index.js";
import { AuditPage } from "./AuditPage";
import { AUDIT_DOMAIN_PARAM, auditDomainsPath, auditRecordsPath, auditVerifyPath } from "./paths";
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
const FIN = "commercial:test:catalog:domain:finance";
const HR = "commercial:test:catalog:domain:people";

let activeFetch: typeof fetch = () => Promise.reject(new Error("useApi() was not called"));

function json(body: unknown, status = 200, type = "application/json"): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": type } });
}

function problem(status: number, code: string, reason: string): Response {
  return json(
    {
      schema_version: "1.0.0",
      type: "https://neurosphere.invalid/problems/x",
      title: "Problem",
      status,
      detail: reason,
      instance: "/x",
      code,
      reason,
      retryable: false,
      correlation_id: "corr-test-1",
    },
    status,
    "application/problem+json",
  );
}

function rec(sequence: number, over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    schema_version: "1.0.0",
    audit_id: `00000000-0000-4000-8000-${String(sequence).padStart(12, "0")}`,
    chain_id: "test.finance",
    sequence,
    previous_hash: null,
    record_hash: `sha256:${"a".repeat(64)}`,
    kind: "after",
    recorded_at: "2026-10-20T10:00:00.000000Z",
    actor: { principal_pseudonym: "psn-test-actor", principal_kind: "user", on_behalf_of: null },
    scope_hash: `sha256:${"b".repeat(64)}`,
    correlation_id: `corr-${sequence}`,
    operation: "action.execute",
    channel: "button",
    intent_id: null,
    subject: {
      target: {
        canonical_id: `commercial:test:catalog:model_deployment:d${sequence}`,
        entity_type: "model_deployment",
      },
      target_version: "v7",
      state_digest: null,
      snapshot_ref: null,
    },
    outcome: { result: "succeeded", verified: true, detail: null },
    denial: null,
    ...over,
  };
}

const DOMAINS = {
  items: [
    { domain_id: FIN, display_name: "Finance", display_name_source: "catalog" },
    { domain_id: HR, display_name: "People", display_name_source: "derived" },
  ],
};

type Handler = (url: URL) => Response;

/** Strict fake API: an unmatched request rejects, so the page cannot call anything unplanned. */
function useApi(handlers: Record<string, Handler>): URL[] {
  const urls: URL[] = [];
  activeFetch = (input) => {
    const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw);
    urls.push(url);
    const handler = handlers[url.pathname];
    return handler === undefined
      ? Promise.reject(new Error(`unhandled request: ${url.pathname}`))
      : Promise.resolve(handler(url));
  };
  return urls;
}

function Where(): null {
  const { search } = useLocation();
  (globalThis as { __search?: string }).__search = search;
  return null;
}

function renderPage(search = "") {
  const client = createApiClient({
    baseUrl: API,
    getToken: () => Promise.resolve("test-credential"),
    fetchImpl: (input, init) => activeFetch(input, init),
    maxRetries: 0,
  });
  return render(
    <QueryProvider client={client}>
      <MemoryRouter initialEntries={[`/audit${search}`]}>
        <AuditPage />
        <Where />
      </MemoryRouter>
    </QueryProvider>,
  );
}

describe("AuditPage", () => {
  it("lists audit domains, selects the first, and shows records as returned", async () => {
    const urls = useApi({
      [auditDomainsPath()]: () => json(DOMAINS),
      [auditRecordsPath(FIN)]: () =>
        json({ items: [rec(0), rec(1, { channel: null })], next_cursor: null }),
    });
    renderPage();
    const rows = await screen.findAllByTestId("audit-row");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByText("psn-test-actor")).toBeTruthy();
    expect(within(rows[0]!).getByText(/version v7/)).toBeTruthy();
    expect(within(rows[1]!).getByText(STRINGS.notRecorded, { selector: "td" })).toBeTruthy();
    expect(screen.getByTestId("audit-end")).toBeTruthy();
    // No export or copy control; no client enrichment calls; no scope keys sent.
    expect(screen.queryByRole("button", { name: /export|copy|download/i })).toBeNull();
    expect(urls.map((u) => u.pathname)).toEqual([auditDomainsPath(), auditRecordsPath(FIN)]);
    for (const u of urls) {
      expect(u.searchParams.has("domain_id")).toBe(false);
      expect(u.searchParams.has("chain_id")).toBe(false);
    }
    expect(urls[1]?.searchParams.get("page_size")).toBe("25");
  });

  it("pages by the server cursor", async () => {
    const urls = useApi({
      [auditDomainsPath()]: () => json(DOMAINS),
      [auditRecordsPath(FIN)]: (url) =>
        url.searchParams.get("cursor") === null
          ? json({ items: [rec(0)], next_cursor: "1" })
          : json({ items: [rec(1)], next_cursor: null }),
    });
    renderPage(`?${AUDIT_DOMAIN_PARAM}=${encodeURIComponent(FIN)}`);
    await screen.findByTestId("audit-more");
    fireEvent.click(screen.getByTestId("audit-more"));
    await waitFor(() => expect(screen.getAllByTestId("audit-row")).toHaveLength(2));
    expect(urls.at(-1)?.searchParams.get("cursor")).toBe("1");
    expect(screen.queryByTestId("audit-more")).toBeNull();
  });

  it("writes the choice to audit_domain, never domain_id", async () => {
    useApi({
      [auditDomainsPath()]: () => json(DOMAINS),
      [auditRecordsPath(FIN)]: () => json({ items: [rec(0)], next_cursor: null }),
      [auditRecordsPath(HR)]: () => json({ items: [], next_cursor: null }),
    });
    renderPage(`?${AUDIT_DOMAIN_PARAM}=${encodeURIComponent(HR)}`);
    await screen.findByTestId("audit-empty");
    const search = (globalThis as { __search?: string }).__search ?? "";
    expect(search).toContain(`${AUDIT_DOMAIN_PARAM}=`);
    expect(search).not.toContain("domain_id");
  });

  it("opens a detail drawer with every field of the record", async () => {
    useApi({
      [auditDomainsPath()]: () => json(DOMAINS),
      [auditRecordsPath(FIN)]: () => json({ items: [rec(4)], next_cursor: null }),
    });
    renderPage();
    fireEvent.click(await screen.findByTestId("audit-open"));
    const drawer = await screen.findByTestId("audit-drawer");
    expect(within(drawer).getByText("Correlation id")).toBeTruthy();
    expect(within(drawer).getByText("corr-4")).toBeTruthy();
    expect(within(drawer).getByText("Record hash")).toBeTruthy();
    expect(screen.getByText(STRINGS.drawerTitle(4))).toBeTruthy();
  });

  it("verifies the chain and reports a break position", async () => {
    useApi({
      [auditDomainsPath()]: () => json(DOMAINS),
      [auditRecordsPath(FIN)]: () => json({ items: [rec(0)], next_cursor: null }),
      [auditVerifyPath(FIN)]: () =>
        json({
          chain_id: "test.finance",
          ok: false,
          records_checked: 3,
          first_invalid_index: 2,
          first_invalid_sequence: 2,
          reason: "record_hash_mismatch",
        }),
    });
    renderPage();
    fireEvent.click(await screen.findByTestId("audit-verify"));
    const result = await screen.findByTestId("audit-verify-result");
    expect(result.textContent).toContain("First break at sequence 2");
    expect(result.textContent).toContain("record_hash_mismatch");
  });

  it("reports a valid chain", async () => {
    useApi({
      [auditDomainsPath()]: () => json(DOMAINS),
      [auditRecordsPath(FIN)]: () => json({ items: [rec(0)], next_cursor: null }),
      [auditVerifyPath(FIN)]: () =>
        json({
          chain_id: "test.finance",
          ok: true,
          records_checked: 12,
          first_invalid_index: null,
          first_invalid_sequence: null,
          reason: null,
        }),
    });
    renderPage();
    fireEvent.click(await screen.findByTestId("audit-verify"));
    expect((await screen.findByTestId("audit-verify-result")).textContent).toBe(
      STRINGS.verifyValid(12),
    );
  });

  it("shows an empty state for an empty chain", async () => {
    useApi({
      [auditDomainsPath()]: () => json(DOMAINS),
      [auditRecordsPath(FIN)]: () => json({ items: [], next_cursor: null }),
    });
    renderPage();
    expect(await screen.findByTestId("audit-empty")).toBeTruthy();
  });

  it("shows ForbiddenState on a 403 from the domain list", async () => {
    useApi({ [auditDomainsPath()]: () => problem(403, "forbidden", "permission_missing") });
    renderPage();
    expect(await screen.findByTestId("forbidden-state")).toBeTruthy();
    expect(screen.queryByTestId("audit-row")).toBeNull();
  });

  it("shows the unconfigured state on a 503 audit_store_unconfigured", async () => {
    useApi({
      [auditDomainsPath()]: () => json(DOMAINS),
      [auditRecordsPath(FIN)]: () =>
        problem(503, "dependency_transient", "audit_store_unconfigured"),
    });
    renderPage();
    expect(await screen.findByTestId("audit-unconfigured")).toBeTruthy();
    expect(screen.queryByTestId("audit-empty")).toBeNull();
  });

  it("does not guess a domain that is not in the audit list", async () => {
    const urls = useApi({ [auditDomainsPath()]: () => json(DOMAINS) });
    renderPage(`?${AUDIT_DOMAIN_PARAM}=commercial%3Atest%3Acatalog%3Adomain%3Aother`);
    expect(await screen.findByTestId("audit-domain-unavailable")).toBeTruthy();
    expect(urls).toHaveLength(1);
  });
});
