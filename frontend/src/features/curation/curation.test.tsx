import type { AccountInfo, IPublicClientApplication } from "@azure/msal-browser";
import { MsalProvider } from "@azure/msal-react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { QueryProvider, createApiClient } from "../../api/index.js";
import { DomainProvider } from "../../app/domain";
import { createStubMsalInstance } from "../../../tests/e2e-support/stubMsal";
import { decisionDiff, expiryToTimestamp, isFuture } from "./data";
import { EdgePage } from "./EdgePage";
import {
  edgeDecisionsPath,
  edgeHref,
  edgeObservationsPath,
  edgeOverridesPath,
  edgePath,
} from "./paths";
import { STRINGS } from "./strings";
import type { PresentedEdge } from "./types";

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
// Contains ":" and "/" on purpose: the id must be encoded in every path.
const EDGE_ID = "commercial:test:catalog:uses_model:agent-a/model-b";

const EDGE: PresentedEdge = {
  edge_id: EDGE_ID,
  relation_type: "uses_model",
  source_id: "commercial:test:catalog:agent:agent-a",
  target_id: "commercial:test:catalog:model_deployment:model-b",
  domain_id: DOMAIN,
  hidden: false,
  status: "inferred",
  confidence: 0.62,
  validity: { valid_from: "2026-09-01T00:00:00Z", valid_to: null },
  lock: { locked: false, reason: null, expiry: null, actor: null },
  curation: null,
  evidence_ids: ["commercial:test:catalog:evidence:e1"],
  security_evidence_ids: ["commercial:test:catalog:evidence:sec1"],
  first_observed: "2026-09-02T08:00:00Z",
  last_observed: "2026-10-20T08:00:00Z",
  pinned: false,
  override_ids: [],
  version: 4,
  etag: "etag-4",
  provenance: { method: "trace_observation", source_id: "connector-a" },
};

const HISTORY = {
  edge_id: EDGE_ID,
  overrides: [
    {
      id: "commercial:test:catalog:edge_override:o1",
      decision: "accept",
      actor: "commercial:test:entra:person:psn_a",
      reason: "checked against the trace",
      decided_at: "2026-10-01T10:00:00Z",
      lock: null,
      set_confidence: null,
    },
  ],
};

const OBS = {
  id: "commercial:test:catalog:evidence:e1",
  observed_at: "2026-10-10T08:00:00Z",
  confidence: 0.7,
  provenance: { method: "trace_observation", source_id: "connector-a" },
  evidence_ids: ["commercial:test:catalog:evidence:e1"],
  security_evidence_ids: ["commercial:test:catalog:evidence:sec1"],
};

function account(roles: readonly string[]): AccountInfo {
  return {
    homeAccountId: "home-curation",
    environment: "login.example.invalid",
    tenantId: "test-tenant",
    username: "someone@example.invalid",
    localAccountId: "local",
    name: "Test User",
    idTokenClaims: { roles: [...roles] },
  };
}

function msalFor(acc: AccountInfo): IPublicClientApplication {
  const base = createStubMsalInstance() as unknown as Record<string, unknown>;
  return {
    ...base,
    getAllAccounts: () => [acc],
    getActiveAccount: () => acc,
  } as unknown as IPublicClientApplication;
}

let activeFetch: typeof fetch = () => Promise.reject(new Error("useApi() was not called"));

function json(body: unknown, status = 200, type = "application/json"): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": type } });
}

function problem(status: number, code: string, reason: string): Response {
  return json(
    {
      type: "about:blank",
      title: code,
      status,
      detail: reason,
      instance: "/x",
      code,
      reason,
      retryable: false,
      correlation_id: "corr-test",
    },
    status,
    "application/problem+json",
  );
}

interface Recorded {
  readonly method: string;
  readonly url: URL;
  readonly body: unknown;
}

interface ApiOptions {
  readonly permissions?: readonly string[];
  readonly edge?: PresentedEdge;
  readonly observations?: () => Response;
  readonly decision?: () => Response;
}

/** Strict fake API: an unmatched request rejects, like MSW's onUnhandledRequest "error". */
function useApi(options: ApiOptions = {}): Recorded[] {
  const calls: Recorded[] = [];
  const edge = options.edge ?? EDGE;
  activeFetch = (input, init) => {
    const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw);
    const method = init?.method ?? "GET";
    const body = typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined;
    calls.push({ method, url, body });
    const p = url.pathname;
    if (p === "/api/v1/me/domains") {
      return Promise.resolve(
        json({
          items: [
            {
              domain_id: DOMAIN,
              display_name: "Finance",
              display_name_source: "catalog",
              cloud: "commercial",
              permissions: options.permissions ?? ["data.read", "catalog.curate"],
            },
          ],
        }),
      );
    }
    if (method === "POST" && p === edgeDecisionsPath(DOMAIN, EDGE_ID)) {
      return Promise.resolve(
        options.decision?.() ?? json({ override: HISTORY.overrides[0], presented: edge }, 201),
      );
    }
    if (method === "GET" && p === edgePath(EDGE_ID)) return Promise.resolve(json(edge));
    if (method === "GET" && p === edgeOverridesPath(EDGE_ID)) return Promise.resolve(json(HISTORY));
    if (method === "GET" && p === edgeObservationsPath(EDGE_ID)) {
      return Promise.resolve(options.observations?.() ?? json({ items: [OBS], next_cursor: null }));
    }
    return Promise.reject(new Error(`unhandled request: ${method} ${p}`));
  };
  return calls;
}

function renderPage(roles: readonly string[] = ["Steward"]) {
  const client = createApiClient({
    baseUrl: API,
    getToken: () => Promise.resolve("test-credential"),
    fetchImpl: (input, init) => activeFetch(input, init),
    maxRetries: 0,
  });
  return render(
    <MsalProvider instance={msalFor(account(roles))}>
      <QueryProvider client={client}>
        <MemoryRouter
          initialEntries={[`${edgeHref(EDGE_ID)}&domain_id=${encodeURIComponent(DOMAIN)}`]}
        >
          <DomainProvider>
            <EdgePage />
          </DomainProvider>
        </MemoryRouter>
      </QueryProvider>
    </MsalProvider>,
  );
}

function local(offsetMs: number): string {
  const d = new Date(Date.now() + offsetMs);
  const pad = (n: number): string => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

async function openDialog(button: string): Promise<HTMLElement> {
  fireEvent.click(await screen.findByRole("button", { name: button }));
  return screen.findByTestId("change-confirm-dialog");
}

function decisionCalls(calls: Recorded[]): Recorded[] {
  return calls.filter((c) => c.method === "POST");
}

describe("paths", () => {
  it("encodes ids with colon and slash and round-trips them", () => {
    for (const path of [
      edgePath(EDGE_ID),
      edgeOverridesPath(EDGE_ID),
      edgeObservationsPath(EDGE_ID),
      edgeDecisionsPath(DOMAIN, EDGE_ID),
    ]) {
      expect(path).toContain("%2F");
      expect(path).toContain("%3A");
      expect(path).not.toContain(EDGE_ID);
    }
    const encoded = edgePath(EDGE_ID).slice(edgePath("").length);
    expect(decodeURIComponent(encoded)).toBe(EDGE_ID);
    const href = new URL(edgeHref(EDGE_ID), "http://x");
    expect(href.searchParams.get("edge_id")).toBe(EDGE_ID);
  });
});

describe("pure helpers", () => {
  it("builds a before/after diff of status, lock and confidence", () => {
    const rows = decisionDiff(EDGE, "lock", 0.9, "soon");
    expect(rows.map((r) => r.field)).toEqual(["Status", "Lock", "Confidence"]);
    expect(rows[0]).toMatchObject({ before: "inferred", after: "curated" });
    expect(rows[2]).toMatchObject({ before: "0.62", after: "0.9" });
  });

  it("converts the local expiry and judges the future", () => {
    expect(expiryToTimestamp("not a date")).toBeNull();
    const stamp = expiryToTimestamp(local(3_600_000));
    expect(stamp).toMatch(/Z$/);
    expect(isFuture(stamp ?? "")).toBe(true);
    expect(isFuture("2020-01-01T00:00:00Z")).toBe(false);
  });
});

describe("edge page", () => {
  it("shows the presented edge, history and security evidence without removal controls", async () => {
    useApi();
    renderPage();
    const summary = await screen.findByTestId("edge-summary");
    expect(within(summary).getByTestId("edge-id")).toHaveTextContent(EDGE_ID);
    expect(within(summary).getByTestId("edge-status")).toHaveTextContent("inferred");
    expect(within(summary).getByTestId("edge-confidence")).toHaveTextContent("0.62");
    expect(within(summary).getByTestId("security-evidence-ids")).toHaveTextContent("sec1");
    expect(within(summary).queryByRole("button")).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: STRINGS.tabs.history }));
    expect(await screen.findByText("checked against the trace")).toBeInTheDocument();
  });

  it("renders observations only after a 200 and pages by cursor", async () => {
    const calls = useApi({
      observations: () => json({ items: [OBS], next_cursor: "c2" }),
    });
    renderPage();
    await screen.findByTestId("edge-summary");
    expect(calls.some((c) => c.url.pathname === edgeObservationsPath(EDGE_ID))).toBe(false);
    fireEvent.click(screen.getByRole("tab", { name: STRINGS.tabs.observations }));
    expect(await screen.findByTestId("observations")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: STRINGS.observations.loadMore }));
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.url.pathname === edgeObservationsPath(EDGE_ID) &&
            c.url.searchParams.get("cursor") === "c2",
        ),
      ).toBe(true),
    );
  });

  it("shows 'Observations need evidence access' on a 403 and no table", async () => {
    useApi({ observations: () => problem(403, "forbidden", "forbidden") });
    renderPage();
    await screen.findByTestId("edge-summary");
    fireEvent.click(screen.getByRole("tab", { name: STRINGS.tabs.observations }));
    expect(await screen.findByTestId("observations-forbidden")).toHaveTextContent(
      "Observations need evidence access",
    );
    expect(screen.queryByTestId("observations")).toBeNull();
  });

  it("hides the decision controls without catalog.curate", async () => {
    useApi({ permissions: ["data.read"] });
    renderPage();
    await screen.findByTestId("edge-summary");
    // The domain list loads in parallel; wait for it before asserting absence.
    await waitFor(() => expect(screen.queryByTestId("decisions")).toBeNull());
    expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();
  });
});

describe("decisions", () => {
  it("accepts with a reason; the body holds only the Item 2 fields and the domain is in the path", async () => {
    const calls = useApi();
    renderPage();
    const dialog = await openDialog("Accept");
    expect(within(dialog).getByTestId("change-target")).toHaveTextContent(EDGE_ID);
    expect(within(dialog).getByTestId("change-version")).toHaveTextContent("4 / etag-4");
    expect(within(dialog).getAllByTestId("change-diff-row")).toHaveLength(3);
    const submit = within(dialog).getByRole("button", { name: "Confirm change" });
    expect(submit).toBeDisabled();
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "verified" } });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    await waitFor(() => expect(decisionCalls(calls)).toHaveLength(1));
    const [call] = decisionCalls(calls);
    expect(call?.url.pathname).toBe(edgeDecisionsPath(DOMAIN, EDGE_ID));
    expect(call?.url.search).toBe("");
    expect(call?.body).toEqual({
      decision: "accept",
      reason: "verified",
      expected_edge_version: 4,
      expected_edge_etag: "etag-4",
    });
    for (const key of ["actor", "domain_id", "customer_id", "decided_at", "channel"]) {
      expect(call?.body).not.toHaveProperty(key);
    }
    expect(await screen.findByTestId("decision-notice")).toHaveTextContent(STRINGS.decide.done);
  });

  it("sends a future lock expiry as a UTC timestamp and refuses a past one without sending", async () => {
    const calls = useApi();
    renderPage();
    const dialog = await openDialog("Lock");
    const reason = within(dialog).getByRole("textbox", { name: /reason/i });
    fireEvent.change(reason, { target: { value: "freeze for audit" } });
    const expiry = dialog.querySelector('input[type="datetime-local"]');
    expect(expiry).not.toBeNull();
    const confirm = within(dialog).getByRole("button", { name: "Confirm change" });
    expect(confirm).toBeDisabled();
    fireEvent.change(expiry as Element, { target: { value: local(-3_600_000) } });
    fireEvent.click(confirm);
    expect(await within(dialog).findByTestId("change-error")).toHaveTextContent(
      STRINGS.decide.expiryPast,
    );
    expect(decisionCalls(calls)).toHaveLength(0);
    fireEvent.change(expiry as Element, { target: { value: local(86_400_000) } });
    fireEvent.click(confirm);
    await waitFor(() => expect(decisionCalls(calls)).toHaveLength(1));
    const body = decisionCalls(calls)[0]?.body as Record<string, unknown>;
    expect(body["decision"]).toBe("lock");
    expect(String(body["lock_expiry"])).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);
    expect(Object.keys(body).sort()).toEqual(
      ["decision", "expected_edge_etag", "expected_edge_version", "lock_expiry", "reason"].sort(),
    );
  });

  it("surfaces a 409 stale_edge with a reload action and never retries", async () => {
    const calls = useApi({ decision: () => problem(409, "stale_version", "stale_edge") });
    renderPage();
    const dialog = await openDialog("Reject");
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "wrong target" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm change" }));
    expect(await within(dialog).findByTestId("decision-error")).toHaveTextContent(
      /changed since you opened it/,
    );
    expect(decisionCalls(calls)).toHaveLength(1);
    const before = calls.filter((c) => c.url.pathname === edgePath(EDGE_ID)).length;
    fireEvent.click(within(dialog).getByRole("button", { name: STRINGS.decide.reload }));
    await waitFor(() =>
      expect(calls.filter((c) => c.url.pathname === edgePath(EDGE_ID)).length).toBeGreaterThan(
        before,
      ),
    );
    expect(decisionCalls(calls)).toHaveLength(1);
  });

  it("shows the service's 403 on a forced submit", async () => {
    useApi({ decision: () => problem(403, "forbidden", "forbidden") });
    renderPage();
    const dialog = await openDialog("Accept");
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "try" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm change" }));
    expect(await within(dialog).findByTestId("decision-error")).toHaveTextContent(
      STRINGS.decide.forbidden,
    );
  });

  it("maps service refusal reasons to readable messages", async () => {
    useApi({ decision: () => problem(422, "invalid_schema", "lock_expiry_not_in_future") });
    renderPage();
    const dialog = await openDialog("Accept");
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "try" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm change" }));
    expect(await within(dialog).findByTestId("decision-error")).toHaveTextContent(
      "The lock expiry must be in the future.",
    );
  });

  it("offers Unlock, not Lock, on a locked edge", async () => {
    useApi({
      edge: {
        ...EDGE,
        lock: { locked: true, reason: "hold", expiry: "2030-01-01T00:00:00Z", actor: "p" },
        pinned: true,
      },
    });
    renderPage();
    expect(await screen.findByRole("button", { name: "Unlock" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Lock" })).toBeNull();
  });

  it("does not offer decisions when the edge carries no version binding", async () => {
    useApi({ edge: { ...EDGE, version: null, etag: null } });
    renderPage();
    const accept = await screen.findByRole("button", { name: "Accept" });
    expect(accept).toBeDisabled();
  });
});
