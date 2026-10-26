import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { QueryProvider, createApiClient } from "../../api/index.js";
import { replayRoutes } from "./routes";
import type { Span, TraceDetail, TracePage } from "./types";

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(cleanup);

const T = "a".repeat(32);

function span(id: string, parent: string | null, over: Partial<Span> = {}): Span {
  return {
    span_id: id.padStart(16, "0"),
    parent_span_id: parent === null ? null : parent.padStart(16, "0"),
    name: `span-${id}`,
    kind: "agent",
    started_at: "2027-01-15T08:00:00.000Z",
    ended_at: null,
    duration_ms: 120,
    status: "ok",
    error: null,
    tool: null,
    agent: null,
    late: false,
    late_reason: null,
    sampled: false,
    sampling_rate: null,
    payload_state: "absent",
    payload: null,
    ...over,
  };
}

const TRACE: TraceDetail = {
  trace_id: T,
  spans: [
    span("1", null, { name: "root-agent", duration_ms: 1500 }),
    span("2", "1", {
      name: "search-tool",
      kind: "tool",
      status: "error",
      error: "timeout",
      tool: { name: "search", outcome: "timeout" },
    }),
    span("3", "1", {
      name: "late-model",
      kind: "model",
      late: true,
      late_reason: "started before its parent",
      duration_ms: null,
    }),
    span("4", "9", { name: "orphan-span", sampled: true, sampling_rate: 0.25 }),
  ],
  gaps: [
    {
      parent_span_id: "9".padStart(16, "0"),
      reason: "sampled_out",
      span_id: "4".padStart(16, "0"),
      count: 1,
      detail: "parent was plausibly dropped by sampling",
    },
  ],
  sampling: { rate: 0.25, reason: "head_sampled" },
  completeness: {
    state: "partial",
    span_count: 4,
    gap_count: 1,
    late_count: 1,
    withheld_span_count: 0,
    truncated: false,
  },
};

const PAGE: TracePage = {
  items: [
    {
      trace_id: T,
      started_at: "2027-01-15T08:00:00.000Z",
      span_count: 4,
      error_count: 1,
      sampling_rate: 0.25,
      root_name: "root-agent",
    },
  ],
  next_cursor: null,
};

function setup(path: string, opts: { page?: TracePage; status?: number } = {}) {
  const fetchImpl = vi.fn<typeof fetch>((input) => {
    if (opts.status !== undefined) {
      return Promise.resolve(new Response("{}", { status: opts.status }));
    }
    const url = String(input);
    const body = /\/traces\/[0-9a-f]{32}/.test(url) ? TRACE : (opts.page ?? PAGE);
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
  });
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("t"),
    fetchImpl,
    maxRetries: 0,
  });
  const router = createMemoryRouter(replayRoutes, { initialEntries: [path] });
  const view = render(
    <QueryProvider client={client}>
      <RouterProvider router={router} />
    </QueryProvider>,
  );
  return { fetchImpl, ...view };
}

const OPEN = `/replay/traces?domain_id=dom-1&trace_id=${T}`;

describe("replay viewer", () => {
  it("renders the span tree with parent-child nesting and durations", async () => {
    setup(OPEN);
    const tree = await screen.findByRole("tree", { name: "Trace spans" });
    const items = within(tree).getAllByRole("treeitem");
    expect(items.length).toBe(4);
    const root = within(tree).getByRole("treeitem", { name: /^root-agent/ });
    expect(root.getAttribute("aria-expanded")).toBe("true");
    expect(within(root).getByText("search-tool")).toBeTruthy();
    expect(within(tree).getByText("1.50 s")).toBeTruthy();
    expect(within(tree).getByText("duration unknown")).toBeTruthy();
  });

  it("labels errors, tools, gaps, sampling and late spans as text", async () => {
    setup(OPEN);
    await screen.findByRole("tree");
    expect(screen.getByTestId("error-badge").textContent).toBe("Error: timeout");
    expect(screen.getByTestId("tool-badge").textContent).toBe("Tool: search (timeout)");
    expect(screen.getByTestId("late-badge").textContent).toBe("Late: started before its parent");
    expect(screen.getByTestId("sampling-badge").textContent).toBe("Sampled at 25%");
    expect(screen.getByTestId("gap-badge").textContent).toBe("Gap: parent sampled out");
    const list = screen.getByTestId("gap-list");
    expect(list.textContent).toContain("Gap: parent sampled out: parent was plausibly dropped");
    expect(screen.getByTestId("completeness").textContent).toContain("Partial trace");
    expect(screen.getByTestId("trace-sampling").textContent).toBe("Sampled at 25% (head_sampled)");
  });

  it("has no axe violations", async () => {
    const { container } = setup(OPEN);
    await screen.findByRole("tree");
    const results = await axe(container);
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });

  it("is keyboard navigable with arrow keys", async () => {
    const user = userEvent.setup();
    setup(OPEN);
    const tree = await screen.findByRole("tree");
    const first = within(tree).getAllByRole("treeitem")[0] as HTMLElement;
    first.focus();
    expect(document.activeElement).toBe(first);
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).not.toBe(first);
    expect(document.activeElement?.getAttribute("role")).toBe("treeitem");
    await user.keyboard("{ArrowLeft}");
    expect(document.activeElement).toBe(first);
  });

  it("has no re-run style control, only GET requests", async () => {
    const { fetchImpl } = setup(OPEN);
    await screen.findByRole("tree");
    const names = screen.queryAllByRole("button").map((b) => b.textContent ?? "");
    expect(names.filter((n) => /re-?run|replay now|execute|retry|invoke/i.test(n))).toEqual([]);
    const methods = fetchImpl.mock.calls.map((c) => (c[1]?.method ?? "GET").toUpperCase());
    expect(new Set(methods)).toEqual(new Set(["GET"]));
    const urls = fetchImpl.mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => u.includes("/api/v1/replay/domains/dom-1/traces/"))).toBe(true);
    expect(urls.some((u) => u.includes("include_payload"))).toBe(false);
  });

  it("shows an empty state when the domain has no traces", async () => {
    setup("/replay/traces?domain_id=dom-1", { page: { items: [], next_cursor: null } });
    expect((await screen.findByTestId("empty-state")).textContent).toBe(
      "No traces found for this domain.",
    );
  });

  it("shows an error state, not an empty list, when the request fails", async () => {
    setup("/replay/traces?domain_id=dom-1", { status: 500 });
    expect(await screen.findByTestId("error-state")).toBeTruthy();
    expect(screen.queryByTestId("empty-state")).toBeNull();
  });

  it("lists traces in a table with relative times and never a raw ISO string", async () => {
    setup("/replay/traces?domain_id=dom-1");
    const table = await screen.findByRole("table", { name: "Traces" });
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((h) => h.textContent);
    expect(headers).toEqual(["Trace", "Root span", "Spans", "Errors", "Started"]);
    const times = table.querySelectorAll("time");
    expect(times.length).toBeGreaterThan(0);
    for (const t of times) {
      expect(t.getAttribute("dateTime")).toMatch(/^\d{4}-\d{2}-\d{2}T/);
      expect(t.textContent ?? "").not.toMatch(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/);
    }
  });

  it("shows a loading state while the traces load", () => {
    const never = vi.fn<typeof fetch>(() => new Promise<Response>(() => undefined));
    const client = createApiClient({
      baseUrl: "http://api.test",
      getToken: () => Promise.resolve("t"),
      fetchImpl: never,
      maxRetries: 0,
    });
    const router = createMemoryRouter(replayRoutes, {
      initialEntries: ["/replay/traces?domain_id=dom-1"],
    });
    render(
      <QueryProvider client={client}>
        <RouterProvider router={router} />
      </QueryProvider>,
    );
    expect(screen.getByTestId("trace-list-loading")).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByTestId("empty-state")).toBeNull();
  });

  it("uses wrapping status pills, never clipping badges, for span annotations", async () => {
    setup(OPEN);
    await screen.findByRole("tree");
    expect(document.querySelector(".fui-Badge")).toBeNull();
    expect(
      within(screen.getByTestId("late-badge")).getByText("Late: started before its parent"),
    ).toHaveAttribute("data-slot", "status-pill");
  });

  it("shows the forbidden state on 403", async () => {
    setup("/replay/traces?domain_id=dom-1", { status: 403 });
    expect(await screen.findByTestId("forbidden-state")).toBeTruthy();
  });

  it("asks for a domain before fetching", () => {
    const { fetchImpl } = setup("/replay/traces");
    expect(screen.getByTestId("domain-required")).toBeTruthy();
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
