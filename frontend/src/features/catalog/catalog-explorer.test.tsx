import type { AccountInfo, IPublicClientApplication } from "@azure/msal-browser";
import { MsalProvider } from "@azure/msal-react";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { QueryProvider, ScopeParameterError, createApiClient } from "../../api/index.js";
import { DomainProvider } from "../../app/domain";
import { createStubMsalInstance } from "../../../tests/e2e-support/stubMsal";
import { CatalogEntityPage } from "./CatalogEntityPage";
import { CatalogExplorerPage } from "./CatalogExplorerPage";
import { RecertificationsPage } from "./RecertificationsPage";
import { StaleAgentsPage } from "./StaleAgentsPage";
import { edgeHref } from "./explorerParts";
import { domainEntitiesPath, entityHref } from "./paths";

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
const DOMAIN = "commercial:e2e:sandbox:domain:finance";
const AGENT = "commercial:e2e:catalog:agent:sample-agent";
const MODEL = "commercial:e2e:catalog:model_deployment:sample-model";
const OWNER = "commercial:e2e:catalog:owner:finance-team";
const EDGE = "commercial:e2e:edge:sample-agent/uses/sample-model";

const account: AccountInfo = {
  homeAccountId: "home-catalog",
  environment: "login.example.invalid",
  tenantId: "test-tenant",
  username: "someone@example.invalid",
  localAccountId: "local",
  name: "Test User",
  idTokenClaims: { roles: ["Steward"] },
};

function msal(): IPublicClientApplication {
  const base = createStubMsalInstance() as unknown as Record<string, unknown>;
  return {
    ...base,
    getAllAccounts: () => [account],
    getActiveAccount: () => account,
  } as unknown as IPublicClientApplication;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": status >= 400 ? "application/problem+json" : "application/json" },
  });
}

interface Call {
  readonly method: string;
  readonly url: URL;
  readonly headers: Headers;
  readonly body: unknown;
}

type Handler = (call: Call) => Response;

/** Strict fake API: a request nobody registered rejects, like MSW `onUnhandledRequest: "error"`. */
function useApi(permissions: readonly string[], routes: Record<string, Handler | Response>) {
  const calls: Call[] = [];
  const fetchImpl: typeof fetch = (input, init) => {
    const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw);
    const method = init?.method ?? "GET";
    const body = typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined;
    const call: Call = { method, url, headers: new Headers(init?.headers), body };
    if (url.pathname === "/api/v1/me/domains") {
      return Promise.resolve(
        json({
          items: [
            {
              domain_id: DOMAIN,
              display_name: "Finance",
              display_name_source: "catalog",
              cloud: "commercial",
              permissions,
            },
          ],
        }),
      );
    }
    calls.push(call);
    const route = routes[`${method} ${url.pathname}`];
    if (route === undefined)
      return Promise.reject(new Error(`unhandled: ${method} ${url.pathname}`));
    return Promise.resolve(typeof route === "function" ? route(call) : route.clone());
  };
  return { calls, fetchImpl };
}

function mount(ui: ReactElement, path: string, fetchImpl: typeof fetch) {
  const client = createApiClient({
    baseUrl: API,
    getToken: () => Promise.resolve("test-credential"),
    fetchImpl,
    maxRetries: 0,
  });
  return render(
    <MsalProvider instance={msal()}>
      <QueryProvider client={client}>
        <DomainProvider>
          <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
        </DomainProvider>
      </QueryProvider>
    </MsalProvider>,
  );
}

function expectNoScopeKeys(calls: readonly Call[]): void {
  for (const call of calls) {
    expect(call.url.searchParams.has("domain_id")).toBe(false);
    expect(call.url.searchParams.has("customer_id")).toBe(false);
    expect(JSON.stringify(call.body ?? {})).not.toMatch(/domain_id|customer_id/);
  }
}

const entity = (id: string, over: Record<string, unknown> = {}) => ({
  id,
  entity_type: "agent",
  domain_id: DOMAIN,
  version: 3,
  etag: "etag-3",
  lifecycle_status: "active",
  updated_at: "2026-10-20T12:00:00Z",
  display_name: id.split(":").pop(),
  ...over,
});

const LIST_PATH = domainEntitiesPath(DOMAIN);
const START = `/catalog?domain_id=${encodeURIComponent(DOMAIN)}`;

describe("paths and guards", () => {
  it("encodes edge ids that contain a colon and a slash", () => {
    expect(edgeHref(EDGE)).toBe(`/catalog/edge?edge_id=${encodeURIComponent(EDGE)}`);
    expect(edgeHref(EDGE)).toContain("%2F");
    expect(entityHref(AGENT)).toBe(`/catalog/entity?entity_id=${encodeURIComponent(AGENT)}`);
  });

  it("the shared client refuses domain_id in a query or a body", async () => {
    const client = createApiClient({
      baseUrl: API,
      getToken: () => Promise.resolve("t"),
      fetchImpl: () => Promise.reject(new Error("must not be sent")),
      maxRetries: 0,
    });
    await expect(
      client.get("/api/v1/catalog/entities", { domain_id: DOMAIN }),
    ).rejects.toBeInstanceOf(ScopeParameterError);
    await expect(
      client.post("/api/v1/catalog/search", { customer_id: "x" }),
    ).rejects.toBeInstanceOf(ScopeParameterError);
  });
});

describe("CatalogExplorerPage", () => {
  const first = {
    items: [entity("a:b:c:agent:one"), entity("a:b:c:agent:two")],
    next_cursor: "c1",
  };
  const second = { items: [entity("a:b:c:agent:three")], next_cursor: null };

  it("lists with N+ while a next page exists and never sends scope keys", async () => {
    const user = userEvent.setup();
    const api = useApi(["data.read"], {
      [`GET ${LIST_PATH}`]: (call) =>
        json(call.url.searchParams.get("cursor") === "c1" ? second : first),
    });
    mount(<CatalogExplorerPage />, START, api.fetchImpl);
    expect(await screen.findByTestId("entity-count")).toHaveTextContent("2+ entities");
    expect(screen.getAllByTestId("entity-row")).toHaveLength(2);
    await user.click(screen.getByTestId("load-more"));
    await waitFor(() => expect(screen.getByTestId("entity-count")).toHaveTextContent("3 entities"));
    expect(screen.queryByTestId("load-more")).toBeNull();
    const cursors = api.calls.map((c) => c.url.searchParams.get("cursor"));
    expect(cursors).toEqual([null, "c1"]);
    expect(api.calls[0]?.url.searchParams.get("page_size")).toBe("25");
    expectNoScopeKeys(api.calls);
  });

  it("links each row to the entity page with an encoded id", async () => {
    const api = useApi(["data.read"], {
      [`GET ${LIST_PATH}`]: json({ items: [entity(AGENT)], next_cursor: null }),
    });
    mount(<CatalogExplorerPage />, START, api.fetchImpl);
    const row = await screen.findByTestId("entity-row");
    expect(within(row).getByRole("link")).toHaveAttribute("href", entityHref(AGENT));
  });

  it("shows an empty state, never a zero total, when nothing matches", async () => {
    const api = useApi(["data.read"], {
      [`GET ${LIST_PATH}`]: json({ items: [], next_cursor: null }),
    });
    mount(<CatalogExplorerPage />, START, api.fetchImpl);
    expect(await screen.findByTestId("empty-state")).toBeInTheDocument();
    expect(screen.queryByTestId("entity-count")).toBeNull();
  });

  it("searches through the domain adapter with a budget and labels a truncated result N+", async () => {
    const user = userEvent.setup();
    const api = useApi(["data.read"], {
      [`GET ${LIST_PATH}`]: json({ items: [entity(AGENT)], next_cursor: null }),
      [`POST /api/v1/catalog/domains/${encodeURIComponent(DOMAIN)}/search`]: json({
        nodes: [entity(AGENT), entity(MODEL, { entity_type: "model_deployment" })],
        edges: [],
        paths: [],
        truncated: true,
        truncated_reason: "max_nodes",
      }),
    });
    mount(<CatalogExplorerPage />, START, api.fetchImpl);
    await screen.findByTestId("entity-row");
    await user.type(screen.getByRole("textbox", { name: "Search entities" }), "sample");
    await user.click(screen.getByTestId("search-submit"));
    expect(await screen.findByTestId("search-truncated")).toBeInTheDocument();
    expect(screen.getByTestId("entity-count")).toHaveTextContent("2+ entities");
    const search = api.calls.find((c) => c.method === "POST");
    expect(search?.body).toMatchObject({ term: "sample", budget: { max_depth: 0 } });
    expectNoScopeKeys(api.calls);
  });

  it("shows the forbidden state when the API says 403", async () => {
    const api = useApi(["data.read"], {
      [`GET ${LIST_PATH}`]: json({ status: 403, code: "forbidden" }, 403),
    });
    mount(<CatalogExplorerPage />, START, api.fetchImpl);
    expect(await screen.findByTestId("forbidden-state")).toBeInTheDocument();
  });

  it("hides export without data.export", async () => {
    const api = useApi(["data.read"], {
      [`GET ${LIST_PATH}`]: json({ items: [entity(AGENT)], next_cursor: null }),
    });
    mount(<CatalogExplorerPage />, START, api.fetchImpl);
    await screen.findByTestId("entity-row");
    expect(screen.queryByTestId("export-json")).toBeNull();
  });

  it("exports JSON pages for data.export holders and handles the API 403", async () => {
    const user = userEvent.setup();
    const created = vi.fn(() => "blob:test");
    const revoked = vi.fn();
    Object.assign(URL, { createObjectURL: created, revokeObjectURL: revoked });
    const exportPath = `/api/v1/catalog/domains/${encodeURIComponent(DOMAIN)}/export`;
    let denied = false;
    const api = useApi(["data.read", "data.export"], {
      [`GET ${LIST_PATH}`]: json({ items: [entity(AGENT)], next_cursor: null }),
      [`GET ${exportPath}`]: (call) =>
        denied
          ? json({ status: 403, code: "forbidden" }, 403)
          : json({
              exported_at: "2026-10-20T12:00:00Z",
              domains: [DOMAIN],
              items: [entity(AGENT)],
              next_cursor: call.url.searchParams.get("cursor") === null ? "p2" : null,
            }),
    });
    mount(<CatalogExplorerPage />, START, api.fetchImpl);
    await user.click(await screen.findByTestId("export-json"));
    await waitFor(() => expect(screen.getByTestId("export-message")).toHaveTextContent("page 1"));
    expect(created).toHaveBeenCalledTimes(1);
    await user.click(screen.getByTestId("export-json"));
    await waitFor(() => expect(screen.getByTestId("export-message")).toHaveTextContent("page 2"));
    expect(
      api.calls
        .filter((c) => c.url.pathname === exportPath)
        .map((c) => c.url.searchParams.get("cursor")),
    ).toEqual([null, "p2"]);
    denied = true;
    await user.click(screen.getByTestId("export-json"));
    await waitFor(() => expect(screen.getByTestId("export-message")).toHaveTextContent("declined"));
    expectNoScopeKeys(api.calls);
    Reflect.deleteProperty(URL, "createObjectURL");
    Reflect.deleteProperty(URL, "revokeObjectURL");
  });
});

const ENTITY_PATH = `/api/v1/catalog/entities/${encodeURIComponent(AGENT)}`;
const OWNER_PATH = `/api/v1/catalog/entities/${encodeURIComponent(OWNER)}`;
const entityUrl = (id: string) => `/catalog/entity?entity_id=${encodeURIComponent(id)}`;

const neighborsBody = {
  nodes: [
    entity(AGENT),
    entity(MODEL, { entity_type: "model_deployment" }),
    entity(OWNER, { entity_type: "owner" }),
  ],
  edges: [
    {
      edge_id: EDGE,
      relation_type: "uses_model",
      source_id: AGENT,
      target_id: MODEL,
      domain_id: DOMAIN,
      status: "asserted",
      confidence: 0.9,
    },
    {
      edge_id: "commercial:e2e:edge:owner",
      relation_type: "owned_by",
      source_id: AGENT,
      target_id: OWNER,
      domain_id: DOMAIN,
      status: "curated",
      confidence: 1,
    },
  ],
  paths: [],
  truncated: true,
  truncated_reason: "max_edges",
};
const impactBody = {
  nodes: [entity(AGENT), entity(MODEL)],
  edges: [],
  paths: [{ node_ids: [AGENT, MODEL], edge_ids: [EDGE] }],
  truncated: false,
  truncated_reason: null,
};
const lineage = {
  "POST /api/v1/catalog/lineage/neighbors": json(neighborsBody),
  "POST /api/v1/catalog/lineage/impact": json(impactBody),
};

describe("CatalogEntityPage", () => {
  it("shows version, ETag, lifecycle, owners and lineage with direction, truncation and links", async () => {
    const api = useApi(["data.read"], { [`GET ${ENTITY_PATH}`]: json(entity(AGENT)), ...lineage });
    mount(<CatalogEntityPage />, entityUrl(AGENT), api.fetchImpl);
    expect(await screen.findByTestId("entity-etag")).toHaveTextContent("etag-3");
    expect(screen.getByTestId("entity-version")).toHaveTextContent("3");
    expect(screen.getByTestId("entity-lifecycle")).toHaveTextContent("active");
    const rows = await screen.findAllByTestId("neighbor-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Outgoing");
    const edgeLink = within(rows[0] as HTMLElement).getByRole("link", { name: EDGE });
    expect(edgeLink).toHaveAttribute("href", edgeHref(EDGE));
    const map = within(rows[0] as HTMLElement).getByRole("link", { name: "Show on map" });
    expect(map).toHaveAttribute("href", `/map?domain_id=${encodeURIComponent(DOMAIN)}`);
    expect(await screen.findByTestId("lineage-truncated")).toHaveTextContent("max_edges");
    expect(await screen.findAllByTestId("impact-row")).toHaveLength(1);
    expect(await screen.findByTestId("entity-owners")).toHaveTextContent("finance-team");
    expectNoScopeKeys(api.calls);
  });

  it("deprecates through the confirm dialog with If-Match and reloads", async () => {
    const user = userEvent.setup();
    let current = entity(AGENT);
    const api = useApi(["data.read"], {
      [`GET ${ENTITY_PATH}`]: () => json(current),
      [`POST ${ENTITY_PATH}/deprecate`]: () => {
        current = entity(AGENT, { version: 4, etag: "etag-4", lifecycle_status: "deprecated" });
        return json(current);
      },
      ...lineage,
    });
    mount(<CatalogEntityPage />, entityUrl(AGENT), api.fetchImpl);
    await user.click(await screen.findByTestId("deprecate-open"));
    expect(await screen.findByTestId("change-target")).toHaveTextContent(AGENT);
    expect(screen.getByTestId("change-version")).toHaveTextContent("etag-3");
    expect(screen.getByTestId("change-diff-row")).toHaveTextContent("deprecated");
    await user.type(screen.getByRole("textbox", { name: /Reason/ }), "replaced by v2");
    await user.click(screen.getByRole("button", { name: "Confirm change" }));
    expect(await screen.findByTestId("change-done")).toHaveTextContent("etag-4");
    const post = api.calls.find(
      (c) => c.method === "POST" && c.url.pathname.endsWith("/deprecate"),
    );
    expect(post?.headers.get("If-Match")).toBe("etag-3");
    await waitFor(() =>
      expect(screen.getByTestId("entity-lifecycle")).toHaveTextContent("deprecated"),
    );
    expect(screen.queryByTestId("deprecate-open")).toBeNull();
    expectNoScopeKeys(api.calls);
  });

  it("explains a 409 as changed since you opened it, reloads and lets the user retry", async () => {
    const user = userEvent.setup();
    let current: Record<string, unknown> = entity(OWNER, {
      entity_type: "owner",
      owner_kind: "team",
      recertified_at: null,
      recertify_by: "2026-10-01T00:00:00Z",
      etag: "etag-old",
    });
    let reads = 0;
    const api = useApi(["data.read"], {
      [`GET ${OWNER_PATH}`]: () => {
        reads += 1;
        return json(current);
      },
      [`POST ${OWNER_PATH}/recertify`]: (call) => {
        if (call.headers.get("If-Match") === "etag-old") {
          current = { ...current, etag: "etag-new" };
          return json({ status: 409, code: "stale_version" }, 409);
        }
        current = { ...current, etag: "etag-final", recertify_by: "2027-10-20T00:00:00Z" };
        return json(current);
      },
      ...lineage,
    });
    mount(<CatalogEntityPage />, entityUrl(OWNER), api.fetchImpl);
    await user.click(await screen.findByTestId("recertify-open"));
    await user.type(await screen.findByRole("textbox", { name: /Reason/ }), "annual review");
    await user.click(screen.getByRole("button", { name: "Confirm change" }));
    expect(await screen.findByTestId("change-error")).toHaveTextContent(
      "changed since you opened it",
    );
    await waitFor(() => expect(screen.getByTestId("change-version")).toHaveTextContent("etag-new"));
    expect(reads).toBeGreaterThanOrEqual(2);
    await user.click(screen.getByRole("button", { name: "Confirm change" }));
    expect(await screen.findByTestId("change-done")).toHaveTextContent("etag-final");
    const posts = api.calls.filter(
      (c) => c.method === "POST" && c.url.pathname.endsWith("/recertify"),
    );
    expect(posts.map((p) => p.headers.get("If-Match"))).toEqual(["etag-old", "etag-new"]);
    expect(posts[0]?.body).toEqual({ valid_for_days: 365 });
    expectNoScopeKeys(api.calls);
  });

  it("shows a 403 on a change inside the dialog", async () => {
    const user = userEvent.setup();
    const api = useApi(["data.read"], {
      [`GET ${ENTITY_PATH}`]: json(entity(AGENT)),
      [`POST ${ENTITY_PATH}/deprecate`]: json({ status: 403, code: "forbidden" }, 403),
      ...lineage,
    });
    mount(<CatalogEntityPage />, entityUrl(AGENT), api.fetchImpl);
    await user.click(await screen.findByTestId("deprecate-open"));
    await user.type(await screen.findByRole("textbox", { name: /Reason/ }), "cleanup");
    await user.click(screen.getByRole("button", { name: "Confirm change" }));
    expect(await screen.findByTestId("change-error")).toHaveTextContent("declined");
  });

  it("asks for an entity when none is chosen", () => {
    const api = useApi(["data.read"], {});
    mount(<CatalogEntityPage />, "/catalog/entity", api.fetchImpl);
    expect(screen.getByTestId("entity-required")).toBeInTheDocument();
    expect(api.calls).toHaveLength(0);
  });
});

describe("RecertificationsPage", () => {
  it("lists due and overdue owners with their domain", async () => {
    const api = useApi(["data.read"], {
      "GET /api/v1/catalog/recertifications": json({
        items: [
          {
            owner_id: OWNER,
            domain_id: DOMAIN,
            owner_kind: "team",
            recertified_at: null,
            recertify_by: "2026-10-01T00:00:00Z",
            state: "overdue",
            days_until_due: -19,
          },
          {
            owner_id: "commercial:e2e:catalog:owner:ops",
            domain_id: DOMAIN,
            owner_kind: "group",
            recertified_at: "2026-07-01T00:00:00Z",
            recertify_by: "2026-11-05T00:00:00Z",
            state: "due",
            days_until_due: 16,
          },
        ],
        scanned: 2,
        next_cursor: null,
      }),
    });
    mount(<RecertificationsPage />, "/catalog/recertifications", api.fetchImpl);
    const rows = await screen.findAllByTestId("recert-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent(DOMAIN);
    expect(rows[0]).toHaveTextContent("Overdue");
    expect(rows[0]).toHaveTextContent("19 days overdue");
    expect(rows[1]).toHaveTextContent("16 days left");
    expect(api.calls[0]?.url.searchParams.get("include")).toBe("both");
    expect(api.calls[0]?.url.searchParams.get("within_days")).toBe("30");
    expectNoScopeKeys(api.calls);
  });

  it("shows the forbidden state for a 403", async () => {
    const api = useApi(["data.read"], {
      "GET /api/v1/catalog/recertifications": json({ status: 403, code: "forbidden" }, 403),
    });
    mount(<RecertificationsPage />, "/catalog/recertifications", api.fetchImpl);
    expect(await screen.findByTestId("forbidden-state")).toBeInTheDocument();
  });
});

describe("StaleAgentsPage", () => {
  const plan = {
    plan_id: "plan-1",
    as_of: "2026-10-20T12:00:00Z",
    window_days: 90,
    candidates: [
      {
        agent_id: "a:b:c:agent:one",
        etag: "e1",
        domain_id: DOMAIN,
        last_observed: "2026-06-01T00:00:00Z",
      },
      {
        agent_id: "a:b:c:agent:two",
        etag: "e2",
        domain_id: DOMAIN,
        last_observed: "2026-06-02T00:00:00Z",
      },
    ],
    truncated: false,
  };

  it("runs dry run, echoes the plan, confirms it and shows per-item outcomes", async () => {
    const user = userEvent.setup();
    const api = useApi(["data.read"], {
      "POST /api/v1/catalog/reconcile/stale-agents/dry-run": json(plan),
      "POST /api/v1/catalog/reconcile/stale-agents/confirm": json({
        plan_id: "plan-1",
        items: [
          { agent_id: "a:b:c:agent:one", status: "marked", code: null, etag: "e9" },
          { agent_id: "a:b:c:agent:two", status: "failed", code: "stale_version", etag: null },
        ],
      }),
    });
    mount(<StaleAgentsPage />, "/catalog/stale-agents", api.fetchImpl);
    await user.click(screen.getByTestId("dry-run"));
    expect(await screen.findAllByTestId("candidate-row")).toHaveLength(2);
    expect(screen.getByTestId("plan-id")).toHaveTextContent("plan-1");
    expect(api.calls).toHaveLength(1);
    expect(api.calls[0]?.body).toEqual({ window_days: 90 });
    await user.click(screen.getByTestId("confirm-open"));
    const dialog = await screen.findByTestId("stale-confirm-dialog");
    expect(within(dialog).getByTestId("plan-id")).toHaveTextContent("plan-1");
    expect(within(dialog).getByTestId("plan-count")).toHaveTextContent("2");
    await user.click(within(dialog).getByTestId("confirm-submit"));
    const outcome = await screen.findAllByTestId("outcome-row");
    expect(outcome[0]).toHaveTextContent("Marked");
    expect(outcome[1]).toHaveTextContent("Failed");
    expect(outcome[1]).toHaveTextContent("stale_version");
    expect(api.calls[1]?.body).toEqual({
      plan_id: "plan-1",
      as_of: "2026-10-20T12:00:00Z",
      window_days: 90,
      candidates: [
        { agent_id: "a:b:c:agent:one", etag: "e1" },
        { agent_id: "a:b:c:agent:two", etag: "e2" },
      ],
    });
    expectNoScopeKeys(api.calls);
  });

  it("does not offer confirm for a truncated or empty plan", async () => {
    const user = userEvent.setup();
    const api = useApi(["data.read"], {
      "POST /api/v1/catalog/reconcile/stale-agents/dry-run": json({ ...plan, truncated: true }),
    });
    mount(<StaleAgentsPage />, "/catalog/stale-agents", api.fetchImpl);
    await user.click(screen.getByTestId("dry-run"));
    expect(await screen.findByTestId("plan-truncated")).toBeInTheDocument();
    expect(screen.getByTestId("confirm-open")).toBeDisabled();
  });

  it("shows a plan mismatch on confirm and keeps nothing marked", async () => {
    const user = userEvent.setup();
    const api = useApi(["data.read"], {
      "POST /api/v1/catalog/reconcile/stale-agents/dry-run": json(plan),
      "POST /api/v1/catalog/reconcile/stale-agents/confirm": json(
        { status: 409, code: "stale_version" },
        409,
      ),
    });
    mount(<StaleAgentsPage />, "/catalog/stale-agents", api.fetchImpl);
    await user.click(screen.getByTestId("dry-run"));
    await user.click(await screen.findByTestId("confirm-open"));
    await user.click(await screen.findByTestId("confirm-submit"));
    expect(await screen.findByTestId("confirm-dialog-error")).toHaveTextContent(
      "no longer matches",
    );
    expect(screen.queryByTestId("outcome")).toBeNull();
  });

  it("shows the forbidden state when dry run is declined", async () => {
    const user = userEvent.setup();
    const api = useApi(["data.read"], {
      "POST /api/v1/catalog/reconcile/stale-agents/dry-run": json(
        { status: 403, code: "forbidden" },
        403,
      ),
    });
    mount(<StaleAgentsPage />, "/catalog/stale-agents", api.fetchImpl);
    await user.click(screen.getByTestId("dry-run"));
    expect(await screen.findByTestId("forbidden-state")).toBeInTheDocument();
  });
});
