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

function setup(path: string, opts: { status?: number; top?: ViewportResponse } = {}) {
  const fetchImpl = vi.fn<typeof fetch>((input) => {
    if (opts.status !== undefined) {
      return Promise.resolve(new Response("{}", { status: opts.status }));
    }
    const url = new URL(String(input));
    let body: ViewportResponse = opts.top ?? TOP;
    if (url.searchParams.get("cluster_id") === "cluster:agents") {
      const cursor = url.searchParams.get("cursor");
      body = clusterPage(cursor === "page-3" ? 3 : cursor === "page-2" ? 2 : 1);
    }
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
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
  return { fetchImpl, ...view };
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
    expect(byHealth.get("ok")?.querySelector("[data-shape='circle-check']")).not.toBeNull();
    expect(byHealth.get("degraded")?.querySelector("[data-shape='triangle']")).not.toBeNull();
    expect(byHealth.get("failing")?.querySelector("[data-shape='octagon']")).not.toBeNull();
    expect(byHealth.get("unknown")?.querySelector("[data-shape='circle-question']")).not.toBeNull();
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
    const rows = within(table).getAllByTestId("edge-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]?.textContent).toBe("Person-3fa9support-agentObserved");
    expect(rows[1]?.textContent).toBe("support-agenttriageDeclared");
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
    expect(within(screen.getByTestId("connections-table")).getAllByTestId("edge-row")).toHaveLength(
      5,
    );
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
