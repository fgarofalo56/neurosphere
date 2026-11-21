import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { QueryProvider, createApiClient } from "../../../api/index.js";
import { domainEntitiesPath, CATALOG_ACCESS_ROUTE } from "../paths";
import { catalogExplorerRoutes } from "../routes";
import { accessDependentsPath, accessQueryPath, accessRegionGroupsPath } from "./hooks";
import { ACCESS_STRINGS as S } from "./strings";
import type {
  AccessDependentsResponse,
  AccessQueryResponse,
  AccessRowView,
  RegionGroupsResponse,
} from "./types";

const DOMAIN = "commercial:contoso:catalog:domain:finance";
const ASSET = "commercial:contoso:catalog:grounding_source:ledger";
const NOW = "2026-10-20T10:00:00Z";

vi.mock("../../../app/domain", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../app/domain")>();
  return {
    ...actual,
    useSelectedDomain: () => ({
      domainId: "commercial:contoso:catalog:domain:finance",
      domains: [],
      setDomain: () => undefined,
      status: "ready" as const,
    }),
  };
});

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});

afterEach(cleanup);

function row(over: Partial<AccessRowView> = {}): AccessRowView {
  return {
    asset_id: ASSET,
    accessor_id: "commercial:contoso:catalog:agent:budget-bot",
    accessor_type: "agent",
    accessor_name: "Budget bot",
    accessor_domain_id: DOMAIN,
    mode: "write",
    relation: "writes",
    edge_id: "commercial:contoso:edge:1",
    status: "inferred",
    confidence: 0.7,
    provenance_method: "data_source_ref",
    provenance_source_id: "telemetry",
    evidence_ids: ["trace:abc"],
    last_observed: NOW,
    depth: 1,
    relation_path: ["writes"],
    path_node_ids: [],
    ...over,
  };
}

const BOUND = { max_assets: 200, max_accessors: 500, timeout_ms: 5000 };

function result(over: Partial<AccessQueryResponse> = {}): AccessQueryResponse {
  return {
    rows: [row()],
    assets: [],
    unassessed_assets: null,
    unassessed_count: null,
    truncated: false,
    truncated_reason: null,
    assets_scanned: 3,
    bound: BOUND,
    ...over,
  };
}

const GROUPS: RegionGroupsResponse = {
  groups: [{ name: "eu", regions: ["francecentral", "swedencentral"] }],
};

interface Reply {
  status: number;
  body: unknown;
}

function problem(status: number, code: string, reason?: string): Reply {
  return {
    status,
    body: {
      type: "about:blank",
      title: code,
      status,
      code,
      retryable: false,
      correlation_id: "corr-1",
      ...(reason !== undefined && { reason }),
    },
  };
}

interface Call {
  method: string;
  path: string;
  body: unknown;
}

function mount(routes: Record<string, Reply>): { calls: Call[] } {
  const calls: Call[] = [];
  const fetchImpl = vi.fn<typeof fetch>((input, init) => {
    const url = new URL(String(input));
    const method = init?.method ?? "GET";
    const body = typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined;
    calls.push({ method, path: url.pathname, body });
    const reply: Reply | undefined = routes[`${method} ${url.pathname}`];
    return Promise.resolve(
      new Response(JSON.stringify(reply?.body ?? { status: 404 }), {
        status: reply?.status ?? 404,
      }),
    );
  });
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("t"),
    fetchImpl,
    maxRetries: 0,
  });
  const router = createMemoryRouter(catalogExplorerRoutes, {
    initialEntries: [`/${CATALOG_ACCESS_ROUTE}`],
  });
  render(
    <QueryProvider client={client}>
      <RouterProvider router={router} />
    </QueryProvider>,
  );
  return { calls };
}

const LIST = `GET ${domainEntitiesPath(DOMAIN)}`;
const QUERY = `POST ${accessQueryPath()}`;
const DEPENDENTS = `POST ${accessDependentsPath()}`;
const REGIONS = `GET ${accessRegionGroupsPath()}`;

const BASE_ROUTES: Record<string, Reply> = {
  [LIST]: {
    status: 200,
    body: {
      items: [
        {
          id: ASSET,
          entity_type: "grounding_source",
          domain_id: DOMAIN,
          display_name: "Ledger store",
          lifecycle_status: "active",
          version: 1,
          etag: "e1",
          updated_at: NOW,
        },
      ],
      next_cursor: null,
    },
  },
  [REGIONS]: { status: 200, body: GROUPS },
};

async function runWrites(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  const select = await screen.findByRole("combobox", { name: S.questions.writes.assetLabel });
  await waitFor(() => expect(within(select).getAllByRole("option").length).toBe(2));
  await user.selectOptions(select, ASSET);
  await user.click(screen.getByTestId("run-writes"));
}

describe("route", () => {
  it("is registered at catalog/access", () => {
    expect(catalogExplorerRoutes.map((r) => r.path)).toContain("catalog/access");
  });
});

describe("who writes to this data asset", () => {
  it("posts the asset with the write mode and renders the evidence table", async () => {
    const { calls } = mount({ ...BASE_ROUTES, [QUERY]: { status: 200, body: result() } });
    const user = userEvent.setup();
    await runWrites(user);
    const table = await screen.findByRole("table", { name: S.results.tableLabel });
    expect(calls.find((c) => c.path === accessQueryPath())?.body).toEqual({
      asset_ids: [ASSET],
      filters: {},
      modes: ["write"],
      include_unassessed: false,
    });
    const r = within(table).getByTestId("access-row");
    expect(within(r).getByRole("link", { name: "Budget bot" }).getAttribute("href")).toBe(
      `/catalog/entity?entity_id=${encodeURIComponent("commercial:contoso:catalog:agent:budget-bot")}`,
    );
    expect(within(r).getByText("Inferred")).toBeTruthy();
    expect(within(r).getByText("70%")).toBeTruthy();
    expect(within(r).getByText("trace:abc")).toBeTruthy();
    expect(within(r).getByText(S.table.modeWrite)).toBeTruthy();
    expect(screen.queryByTestId("partial-banner")).toBeNull();
  });

  it("can ask for readers instead", async () => {
    const { calls } = mount({ ...BASE_ROUTES, [QUERY]: { status: 200, body: result() } });
    const user = userEvent.setup();
    const mode = await screen.findByRole("combobox", { name: S.questions.writes.modeLabel });
    await user.selectOptions(mode, "read");
    await runWrites(user);
    await screen.findByRole("table", { name: S.results.tableLabel });
    expect(
      (calls.find((c) => c.path === accessQueryPath())?.body as { modes: string[] }).modes,
    ).toEqual(["read"]);
  });
});

describe("who touches personal or regulated data", () => {
  it("sends the category and the personal data flag with both modes", async () => {
    const { calls } = mount({ ...BASE_ROUTES, [QUERY]: { status: 200, body: result() } });
    const user = userEvent.setup();
    const run = await screen.findByTestId("run-sensitivity");
    expect((run as HTMLButtonElement).disabled).toBe(true);
    await user.selectOptions(
      screen.getByRole("combobox", { name: S.questions.sensitivity.categoryLabel }),
      "phi",
    );
    await user.click(screen.getByRole("checkbox", { name: S.questions.sensitivity.personalData }));
    await user.click(run);
    await screen.findByRole("table", { name: S.results.tableLabel });
    expect(calls.find((c) => c.path === accessQueryPath())?.body).toEqual({
      asset_ids: [],
      filters: { sensitivity_categories: ["phi"], contains_personal_data: true },
      modes: ["read", "write"],
      include_unassessed: false,
    });
  });

  it("offers pii, phi and cui", async () => {
    mount(BASE_ROUTES);
    const select = await screen.findByRole("combobox", {
      name: S.questions.sensitivity.categoryLabel,
    });
    const values = within(select)
      .getAllByRole("option")
      .map((o) => (o as HTMLOptionElement).value);
    expect(values).toEqual(expect.arrayContaining(["pii", "phi", "cui"]));
  });
});

describe("who touches data held in a region group", () => {
  it("fills the picker from region-groups and sends the group", async () => {
    const { calls } = mount({ ...BASE_ROUTES, [QUERY]: { status: 200, body: result() } });
    const user = userEvent.setup();
    const select = await screen.findByRole("combobox", { name: S.questions.region.groupLabel });
    await waitFor(() => expect(within(select).getAllByRole("option").length).toBe(2));
    expect(screen.getByRole("option", { name: /EU member-state locations/ })).toBeTruthy();
    await user.selectOptions(select, "eu");
    await user.click(screen.getByTestId("run-region"));
    await screen.findByRole("table", { name: S.results.tableLabel });
    expect(calls.find((c) => c.path === accessQueryPath())?.body).toMatchObject({
      filters: { region_group: "eu" },
    });
  });

  it("says so when no group is available", async () => {
    mount({ ...BASE_ROUTES, [REGIONS]: { status: 200, body: { groups: [] } } });
    expect(await screen.findByText(S.questions.region.noGroups)).toBeTruthy();
  });
});

describe("dependents", () => {
  const dependents: AccessDependentsResponse = {
    groups: [
      {
        depth: 1,
        rows: [row({ accessor_name: "Budget bot", mode: null, relation: "invokes", depth: 1 })],
      },
      {
        depth: 2,
        rows: [
          row({
            accessor_id: "commercial:contoso:catalog:agent:report",
            accessor_name: "Report agent",
            mode: null,
            depth: 2,
            edge_id: "e2",
            relation_path: ["invokes", "uses_tool"],
          }),
        ],
      },
    ],
    total: 2,
    truncated: false,
    truncated_reason: null,
    assets_scanned: 2,
    bound: BOUND,
  };

  it("posts the node and depth and groups results by depth with the relation path", async () => {
    const { calls } = mount({ ...BASE_ROUTES, [DEPENDENTS]: { status: 200, body: dependents } });
    const user = userEvent.setup();
    const run = await screen.findByTestId("run-dependents");
    expect((run as HTMLButtonElement).disabled).toBe(true);
    await user.type(screen.getByRole("textbox", { name: /Service or tool id/ }), "svc:ledger");
    await user.selectOptions(screen.getByRole("combobox", { name: S.dependents.depthLabel }), "2");
    await user.click(run);
    const groups = await screen.findAllByTestId("depth-group");
    expect(groups).toHaveLength(2);
    expect(within(groups[0] as HTMLElement).getByText("Budget bot")).toBeTruthy();
    expect(within(groups[1] as HTMLElement).getByText("invokes > uses_tool")).toBeTruthy();
    expect(calls.find((c) => c.path === accessDependentsPath())?.body).toEqual({
      node_id: "svc:ledger",
      max_depth: 2,
    });
  });

  it("offers depth 1 to 5 only", async () => {
    mount(BASE_ROUTES);
    const depth = await screen.findByRole("combobox", { name: S.dependents.depthLabel });
    const values = within(depth)
      .getAllByRole("option")
      .map((o) => (o as HTMLOptionElement).value);
    expect(values).toEqual(["1", "2", "3", "4", "5"]);
  });

  it("shows the partial banner for a truncated walk", async () => {
    mount({
      ...BASE_ROUTES,
      [DEPENDENTS]: {
        status: 200,
        body: { ...dependents, truncated: true, truncated_reason: "max_depth" },
      },
    });
    const user = userEvent.setup();
    await user.type(await screen.findByRole("textbox", { name: /Service or tool id/ }), "svc");
    await user.click(screen.getByTestId("run-dependents"));
    expect(await screen.findByTestId("partial-banner")).toBeTruthy();
  });
});

describe("states", () => {
  it("shows a partial banner naming the reason and the scan count when truncated", async () => {
    mount({
      ...BASE_ROUTES,
      [QUERY]: {
        status: 200,
        body: result({ truncated: true, truncated_reason: "max_assets", assets_scanned: 200 }),
      },
    });
    const user = userEvent.setup();
    await runWrites(user);
    const banner = await screen.findByTestId("partial-banner");
    expect(banner.textContent).toContain(S.results.reasons["max_assets"]);
    expect(banner.textContent).toContain("200 assets were scanned");
    expect(banner.textContent).toContain("do not read this list as complete");
  });

  it("shows the empty state", async () => {
    mount({ ...BASE_ROUTES, [QUERY]: { status: 200, body: result({ rows: [] }) } });
    const user = userEvent.setup();
    await runWrites(user);
    expect(await screen.findByTestId("access-empty")).toBeTruthy();
    expect(screen.queryByRole("table", { name: S.results.tableLabel })).toBeNull();
  });

  it("shows the forbidden state on 403", async () => {
    mount({ ...BASE_ROUTES, [QUERY]: problem(403, "forbidden") });
    const user = userEvent.setup();
    await runWrites(user);
    expect(await screen.findByTestId("forbidden-state")).toBeTruthy();
  });

  it("maps a 422 reason code to human text", async () => {
    mount({ ...BASE_ROUTES, [QUERY]: problem(422, "invalid_schema", "too_many_assets") });
    const user = userEvent.setup();
    await runWrites(user);
    const box = await screen.findByTestId("access-validation");
    expect(box.textContent).toContain(S.errors.validation["too_many_assets"]);
  });

  it("shows a retryable error on a server failure and retries the same request", async () => {
    const { calls } = mount({ ...BASE_ROUTES, [QUERY]: problem(500, "dependency_transient") });
    const user = userEvent.setup();
    await runWrites(user);
    const box = await screen.findByTestId("access-error");
    expect(box.textContent).toContain(S.errors.generic);
    await user.click(within(box).getByRole("button"));
    await waitFor(() => expect(calls.filter((c) => c.path === accessQueryPath())).toHaveLength(2));
  });
});

describe("not assessed", () => {
  const unassessed = [
    {
      id: "commercial:contoso:catalog:grounding_source:legacy",
      display_name: "Legacy store",
      domain_id: DOMAIN,
      classification: null,
      residency_region: null,
      contains_personal_data: null,
      sensitivity_categories: null,
    },
    {
      id: "commercial:contoso:catalog:grounding_source:scratch",
      display_name: "Scratch store",
      domain_id: DOMAIN,
      classification: "internal",
      residency_region: "swedencentral",
      contains_personal_data: null,
      sensitivity_categories: [],
    },
  ];

  it("sends include_unassessed and lists those assets as not assessed, never none", async () => {
    const { calls } = mount({
      ...BASE_ROUTES,
      [QUERY]: {
        status: 200,
        body: result({ unassessed_assets: unassessed, unassessed_count: 2 }),
      },
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("checkbox", { name: S.options.includeUnassessed }));
    await runWrites(user);
    const section = await screen.findByTestId("unassessed-section");
    expect(
      (calls.find((c) => c.path === accessQueryPath())?.body as { include_unassessed: boolean })
        .include_unassessed,
    ).toBe(true);
    expect(within(section).getByText(/2 not assessed/)).toBeTruthy();
    const rows = within(section).getAllByTestId("unassessed-row");
    expect(rows).toHaveLength(2);
    // Legacy: classification, region, flag and categories are all null.
    expect(within(rows[0] as HTMLElement).getAllByText(S.notAssessed)).toHaveLength(4);
    // Scratch: an empty category list and a null flag are still "not assessed".
    expect(within(rows[1] as HTMLElement).getAllByText(S.notAssessed)).toHaveLength(2);
    expect(section.textContent?.toLowerCase()).not.toContain("none");
  });

  it("shows no not assessed section when the server returns none", async () => {
    mount({ ...BASE_ROUTES, [QUERY]: { status: 200, body: result() } });
    const user = userEvent.setup();
    await runWrites(user);
    await screen.findByRole("table", { name: S.results.tableLabel });
    expect(screen.queryByTestId("unassessed-section")).toBeNull();
  });
});

describe("wording", () => {
  it("never claims compliance or certification", () => {
    const text = JSON.stringify(S, (_k, v: unknown) => (typeof v === "function" ? undefined : v));
    expect(text).not.toMatch(/complian|certif|authoriz|authoris/i);
  });
});
