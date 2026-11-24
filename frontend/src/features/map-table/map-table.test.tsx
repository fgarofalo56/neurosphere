import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { QueryProvider, createApiClient } from "../../api/index.js";
import { mapTableRoutes } from "./routes";
import type { NodeMetrics, ViewportEdge, ViewportNode, ViewportResponse } from "./types";

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(cleanup);

const NULL_METRICS: NodeMetrics = {
  tokens: null,
  context_size: null,
  frequency: null,
  latency_p95_ms: null,
  health: "unknown",
};

function node(
  id: string,
  kind: ViewportNode["kind"],
  label: string,
  over: Partial<ViewportNode> = {},
): ViewportNode {
  return {
    id,
    kind,
    label,
    cluster_id: null,
    member_count: null,
    metrics: NULL_METRICS,
    ...over,
  };
}

function edge(id: string, source: string, target: string, p: ViewportEdge["provenance"]) {
  return { id, source, target, provenance: p, last_observed_at: null } satisfies ViewportEdge;
}

const OK: NodeMetrics = {
  tokens: 52000,
  context_size: 8192,
  frequency: 4.5,
  latency_p95_ms: 820,
  health: "ok",
};

const TOP: ViewportResponse = {
  domain_id: "dom-1",
  nodes: [
    node("cluster:agents", "cluster", "Agents", { member_count: 12 }),
    node("a1", "agent", "support-agent", { metrics: OK }),
    node("a2", "sub_agent", "triage", { metrics: { ...OK, health: "degraded" } }),
    node("m1", "model", "gpt", { metrics: { ...OK, health: "failing" } }),
    node("p1", "person", "Person-3fa9"),
  ],
  edges: [edge("e1", "p1", "a1", "observed"), edge("e2", "a1", "a2", "declared")],
  truncated: true,
  truncation_reason: "node_budget",
  next_cursor: null,
  coverage: { state: "partial", lag_seconds: 45, as_of: null },
};

function clusterPage(page: number): ViewportResponse {
  const nodes = [0, 1].map((i) =>
    node(`c:${page}:${i}`, "agent", `member-${page}-${i}`, { cluster_id: "cluster:agents" }),
  );
  return {
    domain_id: "dom-1",
    nodes,
    edges: [edge(`ce${page}`, `c:${page}:0`, `c:${page}:1`, "inferred")],
    truncated: page < 3,
    truncation_reason: page < 3 ? "node_budget" : null,
    next_cursor: page === 1 ? "page-2" : page === 2 ? "page-3" : null,
    coverage:
      page === 2
        ? { state: "delayed", lag_seconds: 300, as_of: null }
        : { state: "complete", lag_seconds: 0, as_of: null },
  };
}

function setup(
  path: string,
  opts: {
    status?: number;
    top?: ViewportResponse;
    gatePage2?: Promise<void>;
    /** Answers search / impact requests; undefined falls through to the viewport fixtures. */
    respond?: (url: URL, init: RequestInit | undefined) => unknown;
  } = {},
) {
  const fetchImpl = vi.fn<typeof fetch>(async (input, init) => {
    if (opts.status !== undefined) {
      return new Response("{}", { status: opts.status });
    }
    const url = new URL(String(input));
    const custom = opts.respond?.(url, init);
    if (custom !== undefined) return new Response(JSON.stringify(custom), { status: 200 });
    let body: ViewportResponse = opts.top ?? TOP;
    if (url.searchParams.get("cluster_id") === "cluster:agents") {
      const cursor = url.searchParams.get("cursor");
      if (cursor === "page-2" && opts.gatePage2 !== undefined) await opts.gatePage2;
      body = clusterPage(cursor === "page-3" ? 3 : cursor === "page-2" ? 2 : 1);
    }
    return new Response(JSON.stringify(body), { status: 200 });
  });
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("t"),
    fetchImpl,
    maxRetries: 0,
  });
  const router = createMemoryRouter(mapTableRoutes, { initialEntries: [path] });
  const view = render(
    <QueryProvider client={client}>
      <RouterProvider router={router} />
    </QueryProvider>,
  );
  return { fetchImpl, router, ...view };
}

const PATH = "/map/table?domain_id=dom-1";

describe("map table", () => {
  it("renders a row per node with kind text and the served label", async () => {
    setup(PATH);
    const grid = await screen.findByRole("treegrid", { name: "Map nodes" });
    const rows = within(grid).getAllByTestId("node-row");
    expect(rows).toHaveLength(5);
    expect(within(rows[4] as HTMLElement).getByTestId("label").textContent).toBe("Person-3fa9");
    expect(within(rows[0] as HTMLElement).getByTestId("kind-text").textContent).toBe("Cluster");
    expect(within(rows[1] as HTMLElement).getByText("820 ms")).toBeTruthy();
  });

  it("shows Unknown text for null metrics, never 0 or blank", async () => {
    setup(PATH);
    const grid = await screen.findByRole("treegrid");
    const person = within(grid).getAllByTestId("node-row")[4] as HTMLElement;
    const cells = Array.from(person.querySelectorAll("td"));
    // tokens, context, frequency, latency
    expect(cells.slice(3, 7).map((c) => c.textContent)).toEqual([
      "Unknown",
      "Unknown",
      "Unknown",
      "Unknown",
    ]);
  });

  it("conveys health by text and distinct icon shape, not colour alone", async () => {
    setup(PATH);
    const grid = await screen.findByRole("treegrid");
    const health = within(grid).getAllByTestId("health");
    const byHealth = new Map(health.map((h) => [h.dataset["health"], h] as const).reverse());
    expect(byHealth.get("ok")?.textContent).toBe("Healthy");
    expect(byHealth.get("degraded")?.textContent).toBe("Degraded");
    expect(byHealth.get("failing")?.textContent).toBe("Failing");
    expect(byHealth.get("unknown")?.textContent).toBe("Unknown");
    // Each state carries its own glyph (the HealthIndicator primitive), so colour is never alone.
    const glyphs = ["ok", "degraded", "failing", "unknown"].map(
      (k) => byHealth.get(k)?.querySelector("[data-slot='health-icon'] svg")?.innerHTML ?? "",
    );
    expect(glyphs.every((g) => g !== "")).toBe(true);
    expect(new Set(glyphs).size).toBe(4);
  });

  it("shows coverage, lag and the truncation reason as text", async () => {
    setup(PATH);
    await screen.findByRole("treegrid");
    expect(screen.getByTestId("coverage").textContent).toBe("Coverage: partial");
    expect(screen.getByTestId("truncation-banner").textContent).toContain("node budget reached");
  });

  it("lists connections with provenance as text", async () => {
    setup(PATH);
    await screen.findByRole("treegrid");
    const table = await screen.findByTestId("connections-table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(rows[0]?.textContent).toBe("Person-3fa9support-agentObserved");
    expect(rows[1]?.textContent).toBe("support-agenttriageDeclared");
  });

  it("renders connections with the design-system table and wrapping provenance pills", async () => {
    setup(PATH);
    await screen.findByRole("treegrid");
    const table = await screen.findByRole("table", { name: "Connections between loaded nodes" });
    expect(within(table).getAllByRole("columnheader")).toHaveLength(3);
    const pills = table.querySelectorAll("[data-slot='status-pill']");
    expect(Array.from(pills).map((p) => p.textContent)).toEqual(["Observed", "Declared"]);
  });

  it("shows a loading state, then the table, and an empty state when there are no nodes", async () => {
    setup(PATH, { top: { ...TOP, nodes: [], edges: [] } });
    expect(screen.getByTestId("map-table-loading")).toHaveAttribute("aria-busy", "true");
    expect(await screen.findByTestId("empty-state")).toHaveTextContent(
      "No nodes found for this domain.",
    );
  });

  it("expands a cluster and loads more pages, showing delayed lag", async () => {
    const user = userEvent.setup();
    const { fetchImpl } = setup(PATH);
    const grid = await screen.findByRole("treegrid");
    const cluster = within(grid).getAllByTestId("node-row")[0] as HTMLElement;
    expect(cluster.getAttribute("aria-expanded")).toBe("false");
    cluster.focus();
    await user.keyboard("{Enter}");
    expect(await within(grid).findByText("member-1-0")).toBeTruthy();
    expect(cluster.getAttribute("aria-expanded")).toBe("true");
    const urls = fetchImpl.mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => u.includes("cluster_id=cluster%3Aagents"))).toBe(true);

    await user.click(screen.getByRole("button", { name: "Load more in Agents" }));
    expect(await within(grid).findByText("member-2-0")).toBeTruthy();
    // focus moves to the first newly loaded row
    await waitFor(() => {
      expect(document.activeElement?.textContent).toContain("member-2-0");
    });
    expect(screen.getByText("Coverage: delayed (300 s lag)")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Load more in Agents" }));
    expect(await within(grid).findByText("member-3-0")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Load more/ })).toBeNull();
    // the cluster's connections joined the connections table
    expect(
      within(screen.getByTestId("connections-table")).getAllByRole("row").slice(1),
    ).toHaveLength(5);
  });

  it("does not steal focus when the user tabbed away while a page was loading", async () => {
    const user = userEvent.setup();
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    setup(PATH, { gatePage2: gate });
    const grid = await screen.findByRole("treegrid");
    const cluster = within(grid).getAllByTestId("node-row")[0] as HTMLElement;
    cluster.focus();
    await user.keyboard("{Enter}");
    expect(await within(grid).findByText("member-1-0")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Load more in Agents" }));
    const outside = screen.getByRole("link");
    outside.focus();
    release();
    expect(await within(grid).findByText("member-2-0")).toBeTruthy();
    await new Promise((r) => setTimeout(r, 20));
    expect(document.activeElement).toBe(outside);
  });

  it("moves between rows with arrow keys and announces the selected row", async () => {
    const user = userEvent.setup();
    setup(PATH);
    const grid = await screen.findByRole("treegrid");
    const rows = within(grid).getAllByTestId("node-row");
    expect(rows[0]?.tabIndex).toBe(0);
    expect(rows[1]?.tabIndex).toBe(-1);
    rows[0]?.focus();
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(rows[1]);
    expect(rows[1]?.tabIndex).toBe(0);
    await user.keyboard("{ArrowDown}{ArrowUp}{End}");
    expect(document.activeElement).toBe(rows[4]);
    await user.keyboard("{Home}");
    expect(document.activeElement).toBe(rows[0]);
    await user.keyboard("{ArrowDown}{Enter}");
    const detail = screen.getByTestId("detail");
    expect(detail.getAttribute("aria-live")).toBe("polite");
    expect(detail.textContent).toContain("Agent support-agent");
    expect(detail.textContent).toContain("health Healthy");
    expect(detail.textContent).toContain("2 loaded connections");
  });

  it("links to the map view", async () => {
    setup(PATH);
    const link = screen.getByRole("link", { name: "View as map" });
    expect(link.getAttribute("href")).toBe("/map?domain_id=dom-1");
  });

  it("asks for a domain before fetching", () => {
    const { fetchImpl } = setup("/map/table");
    expect(screen.getByTestId("domain-required")).toBeTruthy();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("shows the forbidden state on 403, not data", async () => {
    setup(PATH, { status: 403 });
    expect(await screen.findByTestId("forbidden-state")).toBeTruthy();
    expect(screen.queryByRole("treegrid")).toBeNull();
  });

  it("shows sign-in text on 401 and an error on 503", async () => {
    setup(PATH, { status: 401 });
    expect((await screen.findByTestId("error-state")).textContent).toContain("not signed in");
    cleanup();
    setup(PATH, { status: 503 });
    expect((await screen.findByTestId("error-state")).textContent).toContain("not an empty result");
    expect(screen.queryByTestId("empty-state")).toBeNull();
  });

  it("has no axe violations, before and after expansion", async () => {
    const user = userEvent.setup();
    const { container } = setup(PATH);
    const grid = await screen.findByRole("treegrid");
    expect((await axe(container)).violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
    (within(grid).getAllByTestId("node-row")[0] as HTMLElement).focus();
    await user.keyboard("{Enter}");
    await within(grid).findByText("member-1-0");
    expect((await axe(container)).violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
});

// ---- PRP-77 item 5: filters, search, new kinds, facet columns and the impact view ----

const COVERAGE_OK = { state: "complete", lag_seconds: 0, as_of: null } as const;

function searchBody(
  matches: readonly { node: ViewportNode; cluster_id: string }[],
): Record<string, unknown> {
  return {
    domain_id: "dom-1",
    matches,
    counts: {
      by_kind: { agent: 3, model: 1 },
      by_health: { ok: 2, failing: 1, degraded: 1 },
      by_environment: { production: 2, staging: 1 },
      by_cloud: { commercial: 3 },
    },
    truncated: false,
    truncation_reason: null,
    coverage: COVERAGE_OK,
  };
}

const isSearch = (url: URL): boolean => url.pathname.endsWith("/search");
const isImpact = (url: URL): boolean => url.pathname.endsWith("/impact");
const viewportUrls = (fetchImpl: { mock: { calls: unknown[][] } }): URL[] =>
  fetchImpl.mock.calls
    .map((c) => new URL(String(c[0])))
    .filter((u) => u.pathname.endsWith("/viewport"));

function impactBody(rootId: string, levels: { depth: number; nodes: ViewportNode[] }[]) {
  return {
    domain_id: "dom-1",
    node_id: rootId,
    direction: "dependents",
    levels: levels.map((l) => ({
      depth: l.depth,
      nodes: l.nodes.map((n) => ({
        id: n.id,
        kind: n.kind,
        label: n.label,
        domain_id: "dom-1",
        health: n.metrics.health,
      })),
      edge_ids: [],
    })),
    truncated: false,
    truncation_reason: null,
    coverage: COVERAGE_OK,
  };
}

describe("map table: filters (same URL state as the map)", () => {
  it("sends the filters from the URL with the viewport request and shows them in the bar", async () => {
    const { fetchImpl } = setup(`${PATH}&environment=production&health=failing`);
    await screen.findByRole("treegrid");
    const urls = viewportUrls(fetchImpl);
    expect(urls.length).toBeGreaterThan(0);
    for (const u of urls) {
      expect(u.searchParams.get("environment")).toBe("production");
      expect(u.searchParams.get("health")).toBe("failing");
    }
    expect(screen.getByTestId("filter-environment")).toHaveValue("production");
    expect(screen.getByTestId("map-filter-bar")).toHaveAttribute("data-active-filters", "2");
    // the map link carries the same filters
    expect(screen.getByRole("link", { name: "View as map" }).getAttribute("href")).toBe(
      "/map?domain_id=dom-1&environment=production&health=failing",
    );
  });

  it("sends the filters with an expanded cluster's request too", async () => {
    const user = userEvent.setup();
    const { fetchImpl } = setup(`${PATH}&cloud=government`);
    const grid = await screen.findByRole("treegrid");
    (within(grid).getAllByTestId("node-row")[0] as HTMLElement).focus();
    await user.keyboard("{Enter}");
    await within(grid).findByText("member-1-0");
    const clusterCalls = viewportUrls(fetchImpl).filter((u) => u.searchParams.has("cluster_id"));
    expect(clusterCalls.length).toBeGreaterThan(0);
    expect(clusterCalls.every((u) => u.searchParams.get("cloud") === "government")).toBe(true);
  });

  it("changing a filter updates the URL and refetches; clear all removes it", async () => {
    const user = userEvent.setup();
    const { fetchImpl, router } = setup(PATH, {
      respond: (url) => (isSearch(url) ? searchBody([]) : undefined),
    });
    await screen.findByRole("treegrid");
    await user.selectOptions(await screen.findByTestId("filter-health"), "failing");
    await waitFor(() => expect(router.state.location.search).toContain("health=failing"));
    expect(router.state.location.search).toContain("domain_id=dom-1");
    await waitFor(() =>
      expect(viewportUrls(fetchImpl).some((u) => u.searchParams.get("health") === "failing")).toBe(
        true,
      ),
    );
    await user.click(await screen.findByTestId("filter-clear"));
    await waitFor(() => expect(router.state.location.search).not.toContain("health="));
  });

  it("rejects an invalid tag in the field before any request", async () => {
    const user = userEvent.setup();
    const { router } = setup(PATH);
    await screen.findByRole("treegrid");
    await user.type(screen.getByTestId("filter-tag"), "Bad Tag!{Enter}");
    expect(router.state.location.search).not.toContain("tag=");
    expect(await screen.findByText(/Not a valid tag/)).toBeTruthy();
  });
});

describe("map table: kinds and facet columns", () => {
  const KINDS: ViewportResponse = {
    ...TOP,
    nodes: [
      node("s1", "service", "billing-api"),
      node("t1", "tool", "web-search"),
      node("x1", "mcp_server", "files-mcp"),
      node("q1", "quantum" as ViewportNode["kind"], "odd-node"),
    ],
    edges: [],
    truncated: false,
    truncation_reason: null,
  };

  it("labels service, tool and MCP server rows and shows an unknown kind by its raw name", async () => {
    setup(PATH, { top: KINDS });
    const grid = await screen.findByRole("treegrid");
    const kinds = within(grid)
      .getAllByTestId("kind-text")
      .map((k) => k.textContent);
    expect(kinds).toEqual(["Service", "Tool", "MCP server", "quantum"]);
  });

  it("shows environment, cloud and error rate as text, Unknown when absent", async () => {
    const top: ViewportResponse = {
      ...TOP,
      nodes: [
        node("a1", "agent", "with-facets", {
          metrics: OK,
          facets: { environment: "production", cloud: "government", error_rate: 0.125 },
        }),
        node("a2", "agent", "no-facets", { metrics: OK }),
        node("a3", "agent", "zero-errors", { metrics: OK, facets: { error_rate: 0 } }),
      ],
      edges: [],
    };
    setup(PATH, { top });
    const grid = await screen.findByRole("treegrid");
    expect(
      within(grid)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual([
      "Kind",
      "Label",
      "Members",
      "Tokens",
      "Context size",
      "Frequency",
      "Latency p95",
      "Health",
      "Environment",
      "Cloud",
      "Error rate",
    ]);
    const rows = within(grid).getAllByTestId("node-row");
    const text = (row: HTMLElement | undefined, id: string): string | null | undefined =>
      row?.querySelector(`[data-testid='${id}']`)?.textContent;
    expect(text(rows[0], "environment")).toBe("Production");
    expect(text(rows[0], "cloud")).toBe("Government");
    expect(text(rows[0], "error-rate")).toBe("12.5%");
    expect(text(rows[1], "environment")).toBe("Unknown");
    expect(text(rows[1], "error-rate")).toBe("Unknown");
    // a measured zero is a zero, not unknown
    expect(text(rows[2], "error-rate")).toBe("0.0%");
  });
});

describe("map table: search focuses the row", () => {
  const MATCH_TOP = { node: TOP.nodes[1] as ViewportNode, cluster_id: "cluster:agents" };
  const MATCH_MEMBER = {
    node: node("c:1:0", "agent", "member-1-0", { cluster_id: "cluster:agents" }),
    cluster_id: "cluster:agents",
  };
  const MATCH_UNLOADED = {
    node: node("c:9:9", "agent", "far-member", { cluster_id: "cluster:agents" }),
    cluster_id: "cluster:agents",
  };
  const MATCH_NOWHERE = {
    node: node("z:1", "agent", "stranger", { cluster_id: "cluster:gone" }),
    cluster_id: "cluster:gone",
  };

  async function searchAndPick(user: ReturnType<typeof userEvent.setup>, text: string) {
    await user.type(screen.getByTestId("map-search"), text);
    const results = await screen.findAllByTestId("map-search-result", {}, { timeout: 3000 });
    await user.click(results[0] as HTMLElement);
  }

  function withMatch(m: { node: ViewportNode; cluster_id: string }) {
    return { respond: (url: URL) => (isSearch(url) ? searchBody([m]) : undefined) };
  }

  it("focuses a row that is already loaded and selects it", async () => {
    const user = userEvent.setup();
    setup(PATH, withMatch(MATCH_TOP));
    await screen.findByRole("treegrid");
    await searchAndPick(user, "supp");
    await waitFor(() => {
      expect(document.activeElement?.getAttribute("data-row-key")).toBe("root|a1");
    });
    expect(screen.getByTestId("detail").textContent).toContain("Agent support-agent");
    expect(screen.getByTestId("search-note").textContent).toBe(
      "Focused support-agent in the table.",
    );
  });

  it("opens the cluster to reach a member, then focuses its row", async () => {
    const user = userEvent.setup();
    setup(PATH, withMatch(MATCH_MEMBER));
    const grid = await screen.findByRole("treegrid");
    expect(within(grid).queryByText("member-1-0")).toBeNull();
    await searchAndPick(user, "memb");
    await waitFor(() => {
      expect(document.activeElement?.getAttribute("data-row-key")).toBe(
        "root|cluster:agents|c:1:0",
      );
    });
    expect(within(grid).getAllByTestId("node-row")[0]).toHaveAttribute("aria-expanded", "true");
  });

  it("says in text when the row is in a cluster page that is not loaded", async () => {
    const user = userEvent.setup();
    setup(PATH, withMatch(MATCH_UNLOADED));
    await screen.findByRole("treegrid");
    await searchAndPick(user, "far");
    await waitFor(() => {
      expect(screen.getByTestId("search-note").textContent).toBe(
        'far-member is in Agents but is not loaded yet. Use "Load more" in Agents.',
      );
    });
  });

  it("says in text when the row is not in the table with the current filters", async () => {
    const user = userEvent.setup();
    setup(PATH, withMatch(MATCH_NOWHERE));
    await screen.findByRole("treegrid");
    await searchAndPick(user, "stra");
    await waitFor(() => {
      expect(screen.getByTestId("search-note").textContent).toContain(
        "stranger is not in the table with the current filters",
      );
    });
  });

  it("sends the active filters with the search request", async () => {
    const user = userEvent.setup();
    const { fetchImpl } = setup(`${PATH}&health=ok`, withMatch(MATCH_TOP));
    await screen.findByRole("treegrid");
    await user.type(screen.getByTestId("map-search"), "supp");
    await screen.findAllByTestId("map-search-result", {}, { timeout: 3000 });
    const searches = fetchImpl.mock.calls
      .map((c) => new URL(String(c[0])))
      .filter((u) => isSearch(u) && u.searchParams.get("q") === "supp");
    expect(searches.length).toBeGreaterThan(0);
    expect(searches[0]?.searchParams.get("health")).toBe("ok");
  });
});

describe("map table: impact view", () => {
  const IMPACT_RESPONDER = (depths: number[]) => (url: URL, init: RequestInit | undefined) => {
    if (isSearch(url)) return searchBody([]);
    if (!isImpact(url)) return undefined;
    depths.push(JSON.parse(String(init?.body)).max_depth as number);
    return impactBody("a1", [
      { depth: 1, nodes: [TOP.nodes[2] as ViewportNode] },
      { depth: 2, nodes: [TOP.nodes[3] as ViewportNode] },
    ]);
  };

  it("adds a depth column, filters to affected rows, announces the count and restores on clear", async () => {
    const user = userEvent.setup();
    const depths: number[] = [];
    setup(PATH, { respond: IMPACT_RESPONDER(depths) });
    const grid = await screen.findByRole("treegrid");
    expect(screen.getByTestId("show-impact")).toBeDisabled();
    const row = within(grid).getAllByTestId("node-row")[1] as HTMLElement;
    row.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByTestId("show-impact")).toBeEnabled();
    await user.click(screen.getByTestId("show-impact"));

    await waitFor(() =>
      expect(screen.getByTestId("impact-status").textContent).toContain(
        "2 dependents affected by support-agent",
      ),
    );
    expect(screen.getByTestId("impact-status")).toHaveAttribute("aria-live", "polite");
    expect(depths).toEqual([2]);
    expect(
      within(grid)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toContain("Depth");
    const rows = within(grid).getAllByTestId("node-row");
    expect(rows.map((r) => r.querySelector("[data-testid='label']")?.textContent)).toEqual([
      "support-agent",
      "triage",
      "gpt",
    ]);
    expect(rows.map((r) => r.querySelector("[data-testid='depth']")?.textContent)).toEqual([
      "Selected",
      "1",
      "2",
    ]);

    // exactly one row stays tabbable after the filter
    expect(grid.querySelectorAll("tr[data-row-key][tabindex='0']")).toHaveLength(1);

    await user.click(screen.getByTestId("show-impact"));
    expect(within(grid).getAllByTestId("node-row")).toHaveLength(5);
    expect(
      within(grid)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).not.toContain("Depth");
    expect(screen.getByTestId("impact-status").textContent).toBe("");
  });

  it("changes the depth with the 1 to 5 control and asks again", async () => {
    const user = userEvent.setup();
    const depths: number[] = [];
    setup(PATH, { respond: IMPACT_RESPONDER(depths) });
    const grid = await screen.findByRole("treegrid");
    (within(grid).getAllByTestId("node-row")[1] as HTMLElement).focus();
    await user.keyboard("{Enter}");
    await user.click(screen.getByTestId("show-impact"));
    const select = await screen.findByTestId("impact-depth");
    expect(Array.from(select.querySelectorAll("option")).map((o) => o.value)).toEqual([
      "1",
      "2",
      "3",
      "4",
      "5",
    ]);
    expect(select).toHaveValue("2");
    await user.selectOptions(select, "4");
    await waitFor(() => expect(depths).toEqual([2, 4]));
  });

  it("toggles with the I key on the focused row and clears with it", async () => {
    const user = userEvent.setup();
    const depths: number[] = [];
    setup(PATH, { respond: IMPACT_RESPONDER(depths) });
    const grid = await screen.findByRole("treegrid");
    const row = within(grid).getAllByTestId("node-row")[1] as HTMLElement;
    row.focus();
    await user.keyboard("i");
    await waitFor(() => expect(within(grid).getAllByTestId("node-row")).toHaveLength(3));
    expect(screen.getByTestId("show-impact")).toHaveTextContent("Clear impact view");
    (within(grid).getAllByTestId("node-row")[0] as HTMLElement).focus();
    await user.keyboard("i");
    await waitFor(() => expect(within(grid).getAllByTestId("node-row")).toHaveLength(5));
  });

  it("is operable by keyboard from the button and does not offer impact for a cluster", async () => {
    const user = userEvent.setup();
    const depths: number[] = [];
    setup(PATH, { respond: IMPACT_RESPONDER(depths) });
    const grid = await screen.findByRole("treegrid");
    const clusterRow = within(grid).getAllByTestId("node-row")[0] as HTMLElement;
    clusterRow.focus();
    await user.keyboard("i"); // a cluster has no impact
    expect(depths).toEqual([]);
    await user.keyboard("{Enter}"); // selects (and expands) the cluster
    expect(screen.getByTestId("show-impact")).toBeDisabled();
    expect(screen.getByText("Impact is shown for single nodes, not clusters.")).toBeTruthy();
    (within(grid).getAllByTestId("node-row")[1] as HTMLElement).focus();
    await user.keyboard("{Enter}");
    screen.getByTestId("show-impact").focus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(depths).toEqual([2]));
  });

  it("lists affected nodes that are not loaded in the table, as text", async () => {
    const user = userEvent.setup();
    const far = node("far:1", "agent", "far-agent", { metrics: OK });
    setup(PATH, {
      respond: (url) => {
        if (isSearch(url)) return searchBody([]);
        if (isImpact(url)) return impactBody("a1", [{ depth: 1, nodes: [far] }]);
        return undefined;
      },
    });
    const grid = await screen.findByRole("treegrid");
    (within(grid).getAllByTestId("node-row")[1] as HTMLElement).focus();
    await user.keyboard("i");
    expect((await screen.findByTestId("impact-not-loaded")).textContent).toBe(
      "1 affected node is not loaded in the table: far-agent. Expand its cluster to load more.",
    );
    expect(screen.getByTestId("impact-status").textContent).toContain(
      "1 dependent affected by support-agent",
    );
  });

  it("has no axe violations with the filter bar, search and impact view open", async () => {
    const user = userEvent.setup();
    const { container } = setup(PATH, { respond: IMPACT_RESPONDER([]) });
    const grid = await screen.findByRole("treegrid");
    (within(grid).getAllByTestId("node-row")[1] as HTMLElement).focus();
    await user.keyboard("i");
    await waitFor(() => expect(within(grid).getAllByTestId("node-row")).toHaveLength(3));
    expect((await axe(container)).violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
});
