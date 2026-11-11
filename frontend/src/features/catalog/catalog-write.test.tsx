import type { AccountInfo, IPublicClientApplication } from "@azure/msal-browser";
import { MsalProvider } from "@azure/msal-react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { QueryProvider, createApiClient } from "../../api/index.js";
import { DomainProvider } from "../../app/domain";
import { createStubMsalInstance } from "../../../tests/e2e-support/stubMsal";
import { CatalogEntityPage } from "./CatalogEntityPage";
import { CatalogExplorerPage } from "./CatalogExplorerPage";
import { SERVER_OWNED_KEYS, buildBody, initialValues, validate } from "./entityFormModel";
import { domainEntitiesPath, domainEntityPath, entityHref } from "./paths";

// PRP-31 round 2 item 10: reason-code picker, create and edit through ChangeConfirmDialog.

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
const OWNER = "commercial:e2e:catalog:owner:finance-team";
const NEW_ID = "commercial:e2e:catalog:agent:new-agent-2";

const account: AccountInfo = {
  homeAccountId: "home-catalog-write",
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

/** Strict fake API: a request nobody registered rejects. */
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

function Probe(): ReactElement {
  const location = useLocation();
  return <p data-testid="location">{`${location.pathname}${location.search}`}</p>;
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
          <MemoryRouter initialEntries={[path]}>
            <Routes>
              <Route path="/catalog" element={ui} />
              <Route path="/catalog/entity" element={ui} />
            </Routes>
            <Probe />
          </MemoryRouter>
        </DomainProvider>
      </QueryProvider>
    </MsalProvider>,
  );
}

const entity = (id: string, over: Record<string, unknown> = {}) => ({
  id,
  entity_type: "agent",
  domain_id: DOMAIN,
  cloud: "commercial",
  customer_id: "e2e",
  schema_version: "1.0.0",
  created_at: "2026-10-01T00:00:00Z",
  version: 3,
  etag: "etag-3",
  lifecycle_status: "active",
  updated_at: "2026-10-20T12:00:00Z",
  display_name: "Sample agent",
  platform: "foundry",
  source_id: "foundry-main",
  agent_kind: "assistant",
  classification: "internal",
  ...over,
});

const ENTITY_PATH = `/api/v1/catalog/entities/${encodeURIComponent(AGENT)}`;
const OWNER_PATH = `/api/v1/catalog/entities/${encodeURIComponent(OWNER)}`;
const LIST_PATH = domainEntitiesPath(DOMAIN);
const START = `/catalog?domain_id=${encodeURIComponent(DOMAIN)}`;
const lineage = {
  "POST /api/v1/catalog/lineage/neighbors": json({
    nodes: [],
    edges: [],
    paths: [],
    truncated: false,
    truncated_reason: null,
  }),
  "POST /api/v1/catalog/lineage/impact": json({
    nodes: [],
    edges: [],
    paths: [],
    truncated: false,
    truncated_reason: null,
  }),
};

function entityUrl(id: string): string {
  return `/catalog/entity?domain_id=${encodeURIComponent(DOMAIN)}&entity_id=${encodeURIComponent(id)}`;
}

function expectNoServerOwned(body: unknown): void {
  expect(body).toBeTypeOf("object");
  const keys = Object.keys(body as Record<string, unknown>);
  for (const forbidden of [...SERVER_OWNED_KEYS, "lifecycle_status"]) {
    expect(keys).not.toContain(forbidden);
  }
}

async function pickReasonCode(user: ReturnType<typeof userEvent.setup>, label: string) {
  await user.click(await screen.findByRole("combobox", { name: /Reason code/ }));
  await user.click(await screen.findByRole("option", { name: label }));
}

describe("reason-code picker", () => {
  it("sends reason_code with the deprecate body and drops the not-stored caveat", async () => {
    const user = userEvent.setup();
    const api = useApi(["data.read", "catalog.curate"], {
      [`GET ${ENTITY_PATH}`]: json(entity(AGENT)),
      [`POST ${ENTITY_PATH}/deprecate`]: json(entity(AGENT, { etag: "etag-4" })),
      ...lineage,
    });
    mount(<CatalogEntityPage />, entityUrl(AGENT), api.fetchImpl);
    await screen.findByTestId("deprecate-open");
    await pickReasonCode(user, "Superseded by another entity");
    await user.click(screen.getByTestId("deprecate-open"));
    const note = await screen.findByTestId("change-reason-note");
    expect(note).toHaveTextContent("Superseded by another entity");
    expect(note).not.toHaveTextContent("not stored");
    await user.type(
      await screen.findByRole("textbox", { name: /Reason/, hidden: true }),
      "replaced by v2",
    );
    await user.click(screen.getByRole("button", { name: "Confirm change", hidden: true }));
    await screen.findByTestId("change-done");
    const post = api.calls.find((c) => c.url.pathname.endsWith("/deprecate"));
    expect(post?.body).toEqual({ reason_code: "superseded" });
    expect(post?.headers.get("If-Match")).toBe("etag-3");
  });

  it("sends reason_code with the recertify body next to valid_for_days", async () => {
    const user = userEvent.setup();
    const owner = entity(OWNER, {
      entity_type: "owner",
      owner_kind: "team",
      recertified_at: null,
      recertify_by: "2026-10-01T00:00:00Z",
    });
    const api = useApi(["data.read"], {
      [`GET ${OWNER_PATH}`]: json(owner),
      [`POST ${OWNER_PATH}/recertify`]: json({ ...owner, etag: "etag-4" }),
      ...lineage,
    });
    mount(<CatalogEntityPage />, entityUrl(OWNER), api.fetchImpl);
    await screen.findByTestId("recertify-open");
    await pickReasonCode(user, "Periodic review");
    await user.click(screen.getByTestId("recertify-open"));
    await user.type(await screen.findByRole("textbox", { name: /Reason/, hidden: true }), "annual");
    await user.click(screen.getByRole("button", { name: "Confirm change", hidden: true }));
    await screen.findByTestId("change-done");
    const post = api.calls.find((c) => c.url.pathname.endsWith("/recertify"));
    expect(post?.body).toEqual({ valid_for_days: 365, reason_code: "periodic_review" });
  });

  it("omits reason_code when none is picked", async () => {
    const user = userEvent.setup();
    const api = useApi(["data.read"], {
      [`GET ${ENTITY_PATH}`]: json(entity(AGENT)),
      [`POST ${ENTITY_PATH}/deprecate`]: json(entity(AGENT, { etag: "etag-4" })),
      ...lineage,
    });
    mount(<CatalogEntityPage />, entityUrl(AGENT), api.fetchImpl);
    await user.click(await screen.findByTestId("deprecate-open"));
    await user.type(await screen.findByRole("textbox", { name: /Reason/, hidden: true }), "x");
    await user.click(screen.getByRole("button", { name: "Confirm change", hidden: true }));
    await screen.findByTestId("change-done");
    const post = api.calls.find((c) => c.url.pathname.endsWith("/deprecate"));
    expect(post?.body).toBeUndefined();
  });
});

describe("create and edit visibility", () => {
  it("shows New entity and Edit only with catalog.curate", async () => {
    const readOnly = useApi(["data.read"], {
      [`GET ${LIST_PATH}`]: json({ items: [], next_cursor: null }),
      [`GET ${ENTITY_PATH}`]: json(entity(AGENT)),
      ...lineage,
    });
    mount(<CatalogExplorerPage />, START, readOnly.fetchImpl);
    await screen.findByTestId("empty-state");
    expect(screen.queryByTestId("new-entity")).toBeNull();
    cleanup();
    mount(<CatalogEntityPage />, entityUrl(AGENT), readOnly.fetchImpl);
    await screen.findByTestId("entity-etag");
    expect(screen.queryByTestId("entity-edit")).toBeNull();
    cleanup();

    const curator = useApi(["data.read", "catalog.curate"], {
      [`GET ${LIST_PATH}`]: json({ items: [], next_cursor: null }),
      [`GET ${ENTITY_PATH}`]: json(entity(AGENT)),
      ...lineage,
    });
    mount(<CatalogExplorerPage />, START, curator.fetchImpl);
    expect(await screen.findByTestId("new-entity")).toBeInTheDocument();
    cleanup();
    mount(<CatalogEntityPage />, entityUrl(AGENT), curator.fetchImpl);
    expect(await screen.findByTestId("entity-edit")).toBeInTheDocument();
  });

  it("does not offer Edit for entity types without a form", async () => {
    const api = useApi(["data.read", "catalog.curate"], {
      [`GET ${OWNER_PATH}`]: json(entity(OWNER, { entity_type: "owner", owner_kind: "team" })),
      ...lineage,
    });
    mount(<CatalogEntityPage />, entityUrl(OWNER), api.fetchImpl);
    await screen.findByTestId("entity-etag");
    expect(screen.queryByTestId("entity-edit")).toBeNull();
  });
});

describe("create", () => {
  it("creates an agent with the domain in the path only and opens the new entity", async () => {
    const user = userEvent.setup();
    const api = useApi(["data.read", "catalog.curate"], {
      [`GET ${LIST_PATH}`]: json({ items: [], next_cursor: null }),
      [`POST ${LIST_PATH}`]: json(entity(NEW_ID, { version: 1, etag: "etag-new" }), 201),
    });
    mount(<CatalogExplorerPage />, START, api.fetchImpl);
    await user.click(await screen.findByTestId("new-entity"));
    // Required fields block the review step.
    await user.click(await screen.findByTestId("entity-form-review"));
    expect(screen.queryByTestId("change-confirm-dialog")).toBeNull();
    expect((await screen.findAllByText("This field is required.")).length).toBeGreaterThan(0);

    await user.type(screen.getByRole("textbox", { name: /Display name/ }), "New agent");
    await user.type(screen.getByRole("textbox", { name: /Platform/ }), "foundry");
    await user.type(screen.getByRole("textbox", { name: /Source id/ }), "foundry-main");
    await user.click(screen.getByTestId("entity-form-review"));

    expect(await screen.findByTestId("change-target", {}, { timeout: 5000 })).toHaveTextContent(
      `New agent in ${DOMAIN}`,
    );
    const rows = screen.getAllByTestId("change-diff-row").map((r) => r.textContent ?? "");
    expect(rows.some((r) => r.includes("display_name") && r.includes("New agent"))).toBe(true);
    await user.type(
      await screen.findByRole("textbox", { name: /Reason/, hidden: true }),
      "onboarding a new agent",
    );
    await user.click(screen.getByRole("button", { name: "Confirm change", hidden: true }));

    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        `/catalog/entity?entity_id=${encodeURIComponent(NEW_ID)}`,
      ),
    );
    const post = api.calls.find((c) => c.method === "POST");
    expect(post?.url.pathname).toBe(LIST_PATH);
    expect(post?.url.search).toBe("");
    expect(post?.body).toEqual({
      entity_type: "agent",
      display_name: "New agent",
      platform: "foundry",
      source_id: "foundry-main",
      agent_kind: "unknown",
      classification: "unknown",
    });
    expectNoServerOwned(post?.body);
    expect(entityHref(NEW_ID)).toContain("entity_id=");
  });

  it("shows a 422 inside the dialog", async () => {
    const user = userEvent.setup();
    const api = useApi(["data.read", "catalog.curate"], {
      [`GET ${LIST_PATH}`]: json({ items: [], next_cursor: null }),
      [`POST ${LIST_PATH}`]: json({ status: 422, code: "invalid_schema" }, 422),
    });
    mount(<CatalogExplorerPage />, START, api.fetchImpl);
    await user.click(await screen.findByTestId("new-entity"));
    await user.type(screen.getByRole("textbox", { name: /Display name/ }), "New agent");
    await user.type(screen.getByRole("textbox", { name: /Platform/ }), "foundry");
    await user.type(screen.getByRole("textbox", { name: /Source id/ }), "foundry-main");
    await user.click(screen.getByTestId("entity-form-review"));
    await user.type(await screen.findByRole("textbox", { name: /Reason/, hidden: true }), "x");
    await user.click(screen.getByRole("button", { name: "Confirm change", hidden: true }));
    expect(await screen.findByTestId("change-error")).toHaveTextContent("rejected");
  });
});

describe("edit", () => {
  async function openEdit(user: ReturnType<typeof userEvent.setup>) {
    await user.click(await screen.findByTestId("entity-edit"));
    const name = await screen.findByRole("textbox", { name: /Display name/ });
    await user.clear(name);
    await user.type(name, "Renamed agent");
    await user.click(screen.getByTestId("entity-form-review"));
  }

  it("PUTs with If-Match, shows the diff and sends no server-owned key", async () => {
    const user = userEvent.setup();
    let current: Record<string, unknown> = entity(AGENT);
    const put = `/api/v1/catalog/domains/${encodeURIComponent(DOMAIN)}/entities/${encodeURIComponent(AGENT)}`;
    expect(domainEntityPath(DOMAIN, AGENT)).toBe(put);
    const api = useApi(["data.read", "catalog.curate"], {
      [`GET ${ENTITY_PATH}`]: () => json(current),
      [`PUT ${put}`]: () => {
        current = { ...current, display_name: "Renamed agent", etag: "etag-4", version: 4 };
        return json(current);
      },
      ...lineage,
    });
    mount(<CatalogEntityPage />, entityUrl(AGENT), api.fetchImpl);
    await openEdit(user);
    expect(await screen.findByTestId("change-target")).toHaveTextContent(AGENT);
    expect(screen.getByTestId("change-version")).toHaveTextContent("etag-3");
    const rows = screen.getAllByTestId("change-diff-row");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("Sample agent");
    expect(rows[0]).toHaveTextContent("Renamed agent");
    await user.type(
      await screen.findByRole("textbox", { name: /Reason/, hidden: true }),
      "fix the name",
    );
    await user.click(screen.getByRole("button", { name: "Confirm change", hidden: true }));
    expect(await screen.findByTestId("change-done")).toHaveTextContent("etag-4");
    const request = api.calls.find((c) => c.method === "PUT");
    expect(request?.headers.get("If-Match")).toBe("etag-3");
    expect(request?.body).toMatchObject({ entity_type: "agent", display_name: "Renamed agent" });
    expectNoServerOwned(request?.body);
    expect(JSON.stringify(request?.body)).not.toMatch(/domain_id|customer_id|"cloud"/);
  });

  it("explains a 409 as changed since you opened it, reloads and retries with the new ETag", async () => {
    const user = userEvent.setup();
    let current: Record<string, unknown> = entity(AGENT, { etag: "etag-old" });
    let reads = 0;
    const put = domainEntityPath(DOMAIN, AGENT);
    const api = useApi(["data.read", "catalog.curate"], {
      [`GET ${ENTITY_PATH}`]: () => {
        reads += 1;
        return json(current);
      },
      [`PUT ${put}`]: (call) => {
        if (call.headers.get("If-Match") === "etag-old") {
          current = { ...current, etag: "etag-new" };
          return json({ status: 409, code: "stale_version" }, 409);
        }
        current = { ...current, display_name: "Renamed agent", etag: "etag-final" };
        return json(current);
      },
      ...lineage,
    });
    mount(<CatalogEntityPage />, entityUrl(AGENT), api.fetchImpl);
    await openEdit(user);
    await user.type(await screen.findByRole("textbox", { name: /Reason/, hidden: true }), "rename");
    await user.click(screen.getByRole("button", { name: "Confirm change", hidden: true }));
    expect(await screen.findByTestId("change-error")).toHaveTextContent(
      "changed since you opened it",
    );
    await waitFor(() => expect(screen.getByTestId("change-version")).toHaveTextContent("etag-new"));
    expect(reads).toBeGreaterThanOrEqual(2);
    await user.click(screen.getByRole("button", { name: "Confirm change", hidden: true }));
    expect(await screen.findByTestId("change-done")).toHaveTextContent("etag-final");
    const puts = api.calls.filter((c) => c.method === "PUT");
    expect(puts.map((p) => p.headers.get("If-Match"))).toEqual(["etag-old", "etag-new"]);
  });
});

describe("form model", () => {
  it("builds a valid mcp_server body with provenance and no server-owned key", () => {
    const values = {
      ...initialValues("mcp_server"),
      display_name: "Finance tools",
      url: "https://finance-tools.example.com/mcp",
      auth_audience: "api://finance-tools",
    };
    expect(validate("mcp_server", values)).toEqual({});
    const body = buildBody("mcp_server", values, { now: "2026-10-20T12:00:00Z" });
    expect(body).toMatchObject({
      entity_type: "mcp_server",
      transport: "streamable_http",
      auth: { kind: "entra", audience: "api://finance-tools" },
      publishable: false,
      provenance: { method: "declared", recorded_at: "2026-10-20T12:00:00Z" },
    });
    expectNoServerOwned(body);
  });

  it("builds model_deployment and tool bodies from their required fields", () => {
    const model = {
      ...initialValues("model_deployment"),
      provider: "azure-openai",
      model_name: "gpt-x",
      deployment_name: "dep-1",
    };
    expect(validate("model_deployment", model)).toEqual({});
    expect(buildBody("model_deployment", model, { now: "t" })).toEqual({
      entity_type: "model_deployment",
      provider: "azure-openai",
      model_name: "gpt-x",
      deployment_name: "dep-1",
      classification: "unknown",
    });
    const tool = { ...initialValues("tool"), display_name: "Writer", source_id: "bad Value" };
    expect(validate("tool", tool)).toEqual({ source_id: "token" });
  });

  it("never lets sse or an api_key upstream be publishable", () => {
    const values = {
      ...initialValues("mcp_server"),
      display_name: "S",
      url: "https://s.example.com/mcp",
      transport: "sse",
      publishable: "true",
    };
    expect(buildBody("mcp_server", values, { now: "t" })["publishable"]).toBe(false);
  });
});
