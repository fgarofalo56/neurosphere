import "@testing-library/jest-dom/vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider, createMemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryProvider, createApiClient } from "../../../api/index.js";
import { ConfigContext } from "../../../app/ConfigContext";
import type { AppConfig } from "../../../app/config";
import { MapView } from "../MapPage";
import type { SearchMatch, ViewportNode, ViewportResponse } from "../types";
import { SearchBox } from "./SearchBox";
import { SEARCH_STRINGS as S } from "./strings";
import { neighbourhoodPath } from "./useJumpToNode";

// jsdom has no WebGL: the renderer is a recorder (sigma is never imported, as in map.test.tsx).
const renderers = vi.hoisted(() => ({ created: [] as { centreOn: ReturnType<typeof vi.fn> }[] }));
vi.mock("../renderer", () => ({
  createMapRenderer: vi.fn(() => {
    const r = {
      fit: vi.fn(),
      update: vi.fn(),
      setEdgeOffset: vi.fn(),
      select: vi.fn(),
      centreOn: vi.fn(),
      setReducedMotion: vi.fn(),
      kill: vi.fn(),
    };
    renderers.created.push(r);
    return r;
  }),
}));
vi.mock("../../../auth/token", () => ({ getToken: vi.fn(() => Promise.resolve("t")) }));

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

const CONFIG: AppConfig = {
  cloud: "commercial",
  tenantId: "t",
  clientId: "c",
  apiBaseUrl: "http://api.test",
  apiScope: "api://x/.default",
};
const COVERAGE = { state: "complete", lag_seconds: 0, as_of: "2026-10-20T10:00:00Z" } as const;
const COUNTS = { by_kind: {}, by_health: {}, by_environment: {}, by_cloud: {} };
const METRICS = {
  tokens: null,
  context_size: null,
  frequency: null,
  latency_p95_ms: null,
  health: "ok",
} as const;

function vnode(id: string, label: string, over: Partial<ViewportNode> = {}): ViewportNode {
  return {
    id,
    kind: "agent",
    label,
    cluster_id: null,
    member_count: null,
    metrics: METRICS,
    ...over,
  };
}

function match(node: ViewportNode): SearchMatch {
  return { node, cluster_id: node.cluster_id ?? "cluster:agents" };
}

const ON_SCREEN = vnode("a1", "support-agent", {
  facets: { environment: "production", health: "failing" },
});
const OFF_SCREEN = vnode("off1", "billing-agent", {
  cluster_id: "cluster:agents",
  facets: { environment: "staging" },
});
const PERSON = vnode("person:Person-3fa9", "Person-3fa9", { kind: "person" });

const VIEWPORT: ViewportResponse = {
  domain_id: "d1",
  nodes: [vnode("cluster:agents", "Agents", { kind: "cluster", member_count: 5 }), ON_SCREEN],
  edges: [],
  truncated: false,
  truncation_reason: null,
  next_cursor: null,
  coverage: COVERAGE,
};

interface Seen {
  readonly url: URL;
  readonly signal: AbortSignal | null | undefined;
}

interface Options {
  /** Matches by query text; "hang" never answers until aborted. */
  readonly matches?: Readonly<Record<string, readonly SearchMatch[] | "hang">>;
  readonly truncated?: boolean;
}

function setup(options: Options = {}) {
  const seen: Seen[] = [];
  const fetchImpl = vi.fn<typeof fetch>((input, init) => {
    const url = new URL(String(input));
    seen.push({ url, signal: init?.signal });
    const json = (body: unknown) =>
      Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
    if (url.pathname.endsWith("/search")) {
      const q = url.searchParams.get("q") ?? "";
      const found = options.matches?.[q] ?? [];
      if (found === "hang") {
        return new Promise<Response>((_, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        });
      }
      return json({
        domain_id: "d1",
        matches: found,
        counts: COUNTS,
        truncated: options.truncated === true,
        truncation_reason: options.truncated === true ? "scan_limit" : null,
        coverage: COVERAGE,
      });
    }
    if (url.pathname.includes("/neighborhood/")) {
      return json({
        domain_id: "d1",
        nodes: [
          OFF_SCREEN,
          vnode("cluster:agents", "Agents", { kind: "cluster", member_count: 5 }),
        ],
        edges: [],
        truncated: true,
        truncation_reason: "node_budget",
        next_cursor: null,
        coverage: COVERAGE,
      });
    }
    return json(VIEWPORT);
  });
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("t"),
    fetchImpl,
    maxRetries: 0,
  });
  const searches = () =>
    seen.filter(
      (s) => s.url.pathname.endsWith("/search") && (s.url.searchParams.get("q") ?? "") !== "",
    );
  const neighbourhoods = () => seen.filter((s) => s.url.pathname.includes("/neighborhood/"));
  return { client, seen, searches, neighbourhoods };
}

function mount(element: React.ReactElement, options: Options = {}, url = "/map") {
  const ctx = setup(options);
  const router = createMemoryRouter([{ path: "/map", element }], { initialEntries: [url] });
  const utils = render(
    <ConfigContext.Provider value={CONFIG}>
      <QueryProvider client={ctx.client}>
        <RouterProvider router={router} />
      </QueryProvider>
    </ConfigContext.Provider>,
  );
  return { ...ctx, ...utils, router };
}

beforeEach(() => {
  renderers.created.length = 0;
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
  vi.stubGlobal("WebSocket", class {});
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: false,
      media: "",
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const input = () => screen.getByTestId("map-search") as HTMLInputElement;
const sleep = (ms: number) => act(async () => void (await new Promise((r) => setTimeout(r, ms))));

describe("useMapSearch request rules", () => {
  it("sends nothing below 2 characters", async () => {
    const user = userEvent.setup();
    const { searches } = mount(<SearchBox domainId="d1" onSelect={vi.fn()} />);
    await user.type(input(), "a");
    await sleep(400);
    expect(searches()).toHaveLength(0);
    expect(screen.getByTestId("map-search-status")).toHaveTextContent("");
  });

  it("collapses a burst of keystrokes into one debounced request with the filters applied", async () => {
    const user = userEvent.setup();
    const { searches } = mount(
      <SearchBox domainId="d1" onSelect={vi.fn()} />,
      { matches: { abc: [match(ON_SCREEN)] } },
      "/map?environment=production",
    );
    await user.type(input(), "abc");
    await waitFor(() => expect(searches()).toHaveLength(1));
    await sleep(400);
    expect(searches()).toHaveLength(1);
    const url = searches()[0]?.url as URL;
    expect(url.pathname).toBe("/api/v1/map/domains/d1/search");
    expect(url.searchParams.get("q")).toBe("abc");
    expect(url.searchParams.get("limit")).toBe("20");
    expect(url.searchParams.get("environment")).toBe("production");
  });

  it("aborts the request in flight on the next keystroke", async () => {
    const user = userEvent.setup();
    const { searches } = mount(<SearchBox domainId="d1" onSelect={vi.fn()} />, {
      matches: { ab: "hang" },
    });
    await user.type(input(), "ab");
    await waitFor(() => expect(searches()).toHaveLength(1));
    const first = searches()[0]?.signal as AbortSignal;
    expect(first.aborted).toBe(false);
    await user.type(input(), "c");
    expect(first.aborted).toBe(true); // immediately, not after the debounce
  });
});

describe("SearchBox", () => {
  it("announces the count in a polite live region and shows kind, environment, health as text", async () => {
    const user = userEvent.setup();
    mount(<SearchBox domainId="d1" onSelect={vi.fn()} />, {
      matches: { ag: [match(ON_SCREEN), match(OFF_SCREEN)] },
    });
    await user.type(input(), "ag");
    await waitFor(() => expect(screen.getAllByTestId("map-search-result")).toHaveLength(2));
    const status = screen.getByTestId("map-search-status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveAttribute("role", "status");
    await waitFor(() => expect(status).toHaveTextContent(S.count(2)));
    const [first, second] = screen.getAllByTestId("map-search-result");
    expect(first).toHaveTextContent("support-agent");
    expect(first).toHaveTextContent("Agent · environment production · health failing");
    expect(second).toHaveTextContent("Agent · environment staging · health ok");
    expect(input()).toHaveAttribute("role", "combobox");
  });

  it("shows only the pseudonym for a person", async () => {
    const user = userEvent.setup();
    mount(<SearchBox domainId="d1" onSelect={vi.fn()} />, {
      matches: { pe: [match(PERSON)] },
    });
    await user.type(input(), "pe");
    const [row] = await screen.findAllByTestId("map-search-result");
    expect(row).toHaveTextContent("Person-3fa9");
    expect(row?.textContent).not.toContain("person:");
  });

  it("shows truncation as text", async () => {
    const user = userEvent.setup();
    mount(<SearchBox domainId="d1" onSelect={vi.fn()} />, {
      matches: { ag: [match(ON_SCREEN)] },
      truncated: true,
    });
    await user.type(input(), "ag");
    expect(await screen.findByTestId("map-search-truncated")).toHaveTextContent(
      S.truncated("scan limit reached"),
    );
  });

  it("supports the keyboard: ArrowDown + Enter selects, Escape closes", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    mount(<SearchBox domainId="d1" onSelect={onSelect} />, {
      matches: { ag: [match(ON_SCREEN), match(OFF_SCREEN)] },
    });
    await user.type(input(), "ag");
    await waitFor(() => expect(input()).toHaveAttribute("aria-expanded", "true"));

    await user.keyboard("{Escape}");
    await waitFor(() => expect(input()).toHaveAttribute("aria-expanded", "false"));

    await user.keyboard("{ArrowDown}");
    await waitFor(() => expect(input()).toHaveAttribute("aria-expanded", "true"));
    await user.keyboard("{ArrowDown}{Enter}");
    await waitFor(() => expect(onSelect).toHaveBeenCalledTimes(1));
    const chosen = onSelect.mock.calls[0]?.[0] as SearchMatch;
    expect(["a1", "off1"]).toContain(chosen.node.id);
  });
});

describe("jump to node", () => {
  async function searchAndPick(label: string, q: string) {
    const user = userEvent.setup();
    await screen.findByTestId("map-search");
    await waitFor(() => expect(screen.getByTestId("node-count")).toHaveTextContent("2"));
    await user.type(input(), q);
    const rows = await screen.findAllByTestId("map-search-result");
    const row = rows.find((r) => r.textContent?.includes(label));
    expect(row).toBeDefined();
    await user.click(row as HTMLElement);
  }

  it("selects and centres a node that is already on screen, without a neighbourhood fetch", async () => {
    const { neighbourhoods } = mount(<MapView domainId="d1" />, {
      matches: { su: [match(ON_SCREEN)] },
    });
    await searchAndPick("support-agent", "su");
    expect(await screen.findByTestId("node-panel")).toBeInTheDocument();
    await waitFor(() => {
      const r = renderers.created.at(-1);
      expect(r?.centreOn).toHaveBeenCalledWith("a1");
    });
    expect(neighbourhoods()).toHaveLength(0);
  });

  it("fetches and merges the neighbourhood for an off-screen node, keeping its cluster", async () => {
    const { neighbourhoods } = mount(<MapView domainId="d1" />, {
      matches: { bi: [match(OFF_SCREEN)] },
    });
    await searchAndPick("billing-agent", "bi");
    await waitFor(() => expect(neighbourhoods()).toHaveLength(1));
    expect((neighbourhoods()[0] as Seen).url.pathname).toBe(neighbourhoodPath("d1", "off1"));
    await waitFor(() => expect(screen.getByTestId("node-count")).toHaveTextContent("3"));
    expect(await screen.findByTestId("node-panel")).toBeInTheDocument();
    await waitFor(() => {
      const r = renderers.created.at(-1);
      expect(r?.centreOn).toHaveBeenCalledWith("off1");
    });
    expect(screen.getByTestId("map-search-jump-note")).toHaveTextContent(
      S.jumpTruncated("node budget reached"),
    );
  });
});
