import "@testing-library/jest-dom/vitest";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider, createMemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryProvider, createApiClient } from "../../../api/index.js";
import { ConfigContext } from "../../../app/ConfigContext";
import type { AppConfig } from "../../../app/config";
import { MapView } from "../MapPage";
import type {
  Health,
  ImpactResponse,
  ViewportEdge,
  ViewportNode,
  ViewportResponse,
} from "../types";
import { IMPACT_STRINGS as S } from "./strings";

// jsdom has no WebGL: the renderer is a recorder (sigma is never imported, as in map.test.tsx).
interface FakeRenderer {
  callbacks: { onSelect(id: string | null): void };
  setImpact: ReturnType<typeof vi.fn>;
  centreOn: ReturnType<typeof vi.fn>;
}
const renderers = vi.hoisted(() => ({ created: [] as unknown[] }));
vi.mock("../renderer", () => ({
  createMapRenderer: vi.fn((_c: unknown, _g: unknown, callbacks: unknown) => {
    const r = {
      callbacks,
      fit: vi.fn(),
      update: vi.fn(),
      setEdgeOffset: vi.fn(),
      select: vi.fn(),
      centreOn: vi.fn(),
      setImpact: vi.fn(),
      setReducedMotion: vi.fn(),
      kill: vi.fn(),
    };
    renderers.created.push(r);
    return r;
  }),
}));
vi.mock("../../../auth/token", () => ({ getToken: vi.fn(() => Promise.resolve("t")) }));
const renderer = (): FakeRenderer => renderers.created.at(-1) as FakeRenderer;

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

class FakeSocket {
  static instances: FakeSocket[] = [];
  onopen: ((e: unknown) => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  onerror: ((e: unknown) => void) | null = null;
  constructor(
    readonly url: string,
    readonly protocols: string[],
  ) {
    FakeSocket.instances.push(this);
  }
  send(): void {}
  close(): void {}
  receive(message: unknown): void {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
}

const CONFIG: AppConfig = {
  cloud: "commercial",
  tenantId: "t",
  clientId: "c",
  apiBaseUrl: "http://api.test",
  apiScope: "api://x/.default",
};
const COVERAGE = { state: "complete", lag_seconds: 0, as_of: "2026-10-20T10:00:00Z" } as const;

function metrics(health: Health) {
  return { tokens: null, context_size: null, frequency: null, latency_p95_ms: null, health };
}
function vnode(id: string, kind: ViewportNode["kind"], label: string, health: Health = "ok") {
  return {
    id,
    kind,
    label,
    cluster_id: null,
    member_count: null,
    metrics: metrics(health),
  } satisfies ViewportNode;
}
const edge = (id: string, source: string, target: string): ViewportEdge => ({
  id,
  source,
  target,
  provenance: "observed",
  last_observed_at: null,
});

const VIEWPORT: ViewportResponse = {
  domain_id: "d1",
  nodes: [
    vnode("s1", "service", "billing-service"),
    vnode("a1", "agent", "support-agent"),
    vnode("a2", "agent", "triage-agent"),
    vnode("x1", "agent", "unrelated-agent"),
  ],
  edges: [edge("e1", "a1", "s1"), edge("e2", "a2", "a1")],
  truncated: false,
  truncation_reason: null,
  next_cursor: null,
  coverage: COVERAGE,
};

const impactNode = (id: string, label: string, health: Health) =>
  ({ id, kind: "agent", label, domain_id: "d1", health }) as const;

function impactFor(nodeId: string, depth: number): ImpactResponse {
  const levels =
    nodeId === "s1"
      ? [
          { depth: 1, nodes: [impactNode("a1", "support-agent", "ok")], edge_ids: ["e1"] },
          ...(depth >= 2
            ? [
                {
                  depth: 2,
                  nodes: [
                    impactNode("a2", "triage-agent", "degraded"),
                    impactNode("off1", "billing-agent", "failing"),
                  ],
                  edge_ids: ["e2"],
                },
              ]
            : []),
        ]
      : [];
  return {
    domain_id: "d1",
    node_id: nodeId,
    direction: "dependents",
    levels,
    truncated: false,
    truncation_reason: null,
    coverage: COVERAGE,
  };
}

interface Posted {
  readonly path: string;
  readonly body: { node_id: string; max_depth: number };
}

function setup() {
  const posts: Posted[] = [];
  const neighbourhoods: string[] = [];
  const fetchImpl = vi.fn<typeof fetch>((input, init) => {
    const url = new URL(String(input));
    const json = (body: unknown) =>
      Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
    if (url.pathname.endsWith("/impact") && init?.method === "POST") {
      const body = JSON.parse(String(init.body)) as Posted["body"];
      posts.push({ path: url.pathname, body });
      return json(impactFor(body.node_id, body.max_depth));
    }
    if (url.pathname.includes("/neighborhood/")) {
      neighbourhoods.push(url.pathname);
      return json({
        ...VIEWPORT,
        nodes: [vnode("off1", "agent", "billing-agent", "failing"), vnode("s1", "service", "x")],
        edges: [],
        truncated: false,
      });
    }
    if (url.pathname.endsWith("/search")) {
      return json({
        domain_id: "d1",
        matches: [],
        counts: { by_kind: {}, by_health: {}, by_environment: {}, by_cloud: {} },
        truncated: false,
        truncation_reason: null,
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
  return { client, posts, neighbourhoods };
}

async function mount() {
  const ctx = setup();
  const router = createMemoryRouter([{ path: "/map", element: <MapView domainId="d1" /> }], {
    initialEntries: ["/map"],
  });
  render(
    <ConfigContext.Provider value={CONFIG}>
      <QueryProvider client={ctx.client}>
        <RouterProvider router={router} />
      </QueryProvider>
    </ConfigContext.Provider>,
  );
  await screen.findByTestId("map-canvas");
  await waitFor(() => expect(FakeSocket.instances).toHaveLength(1));
  const socket = FakeSocket.instances[0] as FakeSocket;
  act(() => socket.onopen?.({}));
  act(() => socket.receive({ type: "subscribed", domain_id: "d1" }));
  await waitFor(() =>
    expect(screen.getByTestId("live-status")).toHaveAttribute("data-live-status", "live"),
  );
  return { ...ctx, socket };
}

let seq = 0;
function delta(socket: FakeSocket, id: string, kind: string, label: string, health: Health): void {
  seq += 1;
  act(() =>
    socket.receive({
      type: "delta",
      domain_id: "d1",
      seq,
      nodes: [{ id, kind, label, cluster_id: null, member_count: null, metrics: metrics(health) }],
      edges: [],
      coverage: COVERAGE,
      emitted_at: "t",
    }),
  );
}

const select = (id: string) => act(() => renderer().callbacks.onSelect(id));
const lastHighlight = () =>
  renderer().setImpact.mock.calls.at(-1)?.[0] as
    { nodeIds: string[]; edgeIds: string[] } | null | undefined;

beforeEach(() => {
  renderers.created.length = 0;
  FakeSocket.instances = [];
  seq = 0;
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
  vi.stubGlobal("WebSocket", FakeSocket);
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
  vi.useRealTimers();
  cleanup();
  vi.unstubAllGlobals();
});

describe("incident view", () => {
  it("Show impact asks the map route for depth 2 and lists dependents by depth with health text", async () => {
    const user = userEvent.setup();
    const { posts } = await mount();
    select("s1");
    await user.click(await screen.findByTestId("show-impact"));
    await screen.findByTestId("impact-list");
    await waitFor(() => expect(screen.getAllByTestId("impact-row")).toHaveLength(3));
    expect(posts).toHaveLength(1);
    expect(posts[0]?.path).toBe("/api/v1/map/domains/d1/impact");
    expect(posts[0]?.body).toEqual({ node_id: "s1", max_depth: 2 });
    expect(screen.getByRole("heading", { name: S.heading })).toBeInTheDocument();
    const depth1 = screen.getByTestId("impact-depth-1");
    expect(within(depth1).getByText(/support-agent, Agent, health Healthy/)).toBeInTheDocument();
    const depth2 = screen.getByTestId("impact-depth-2");
    expect(within(depth2).getByText(/triage-agent, Agent, health Degraded/)).toBeInTheDocument();
  });

  it("highlights the root, the on-screen dependents and their edges; the rest stays dimmed", async () => {
    const user = userEvent.setup();
    await mount();
    select("s1");
    await user.click(await screen.findByTestId("show-impact"));
    await waitFor(() => expect(lastHighlight()?.nodeIds.length).toBe(3));
    expect([...(lastHighlight()?.nodeIds ?? [])].sort()).toEqual(["a1", "a2", "s1"]);
    expect([...(lastHighlight()?.edgeIds ?? [])].sort()).toEqual(["e1", "e2"]);
  });

  it("refetches when the depth changes", async () => {
    const user = userEvent.setup();
    const { posts } = await mount();
    select("s1");
    await user.click(await screen.findByTestId("show-impact"));
    await waitFor(() => expect(screen.getAllByTestId("impact-row")).toHaveLength(3));
    await user.selectOptions(screen.getByTestId("impact-depth"), "1");
    await waitFor(() => expect(posts).toHaveLength(2));
    expect(posts[1]?.body).toEqual({ node_id: "s1", max_depth: 1 });
    await waitFor(() => expect(screen.getAllByTestId("impact-row")).toHaveLength(1));
  });

  it("lists off-screen dependents with a show on map action that uses the shared jump", async () => {
    const user = userEvent.setup();
    const { neighbourhoods } = await mount();
    select("s1");
    await user.click(await screen.findByTestId("show-impact"));
    const offscreen = await screen.findByTestId("impact-offscreen");
    expect(within(offscreen).getByText(/billing-agent, Agent, health Failing/)).toBeInTheDocument();
    await user.click(
      within(offscreen).getByRole("button", { name: S.showOnMapNamed("billing-agent") }),
    );
    await waitFor(() => expect(neighbourhoods).toHaveLength(1));
    expect(neighbourhoods[0]).toBe("/api/v1/map/domains/d1/neighborhood/off1");
    await waitFor(() => expect(renderer().centreOn).toHaveBeenCalledWith("off1"));
  });

  it("clear restores the previous view", async () => {
    const user = userEvent.setup();
    await mount();
    select("s1");
    await user.click(await screen.findByTestId("show-impact"));
    await screen.findByTestId("impact-list");
    await user.click(screen.getByTestId("impact-clear"));
    expect(screen.queryByTestId("impact-list")).not.toBeInTheDocument();
    await waitFor(() => expect(lastHighlight()).toBeNull());
  });

  it("says in a polite live region how many dependents are affected", async () => {
    const user = userEvent.setup();
    await mount();
    select("s1");
    await user.click(await screen.findByTestId("show-impact"));
    const status = await screen.findByTestId("impact-status");
    expect(status).toHaveAttribute("aria-live", "polite");
    await waitFor(() => expect(status).toHaveTextContent(S.affected(3, "billing-service")));
  });

  it("documents the keyboard shortcut and toggles with it", async () => {
    const user = userEvent.setup();
    const { posts } = await mount();
    select("s1");
    expect(await screen.findByTestId("node-panel")).toHaveTextContent(S.shortcut);
    await user.keyboard("i");
    await screen.findByTestId("impact-list");
    expect(posts[0]?.body.node_id).toBe("s1");
    await user.keyboard("i");
    expect(screen.queryByTestId("impact-list")).not.toBeInTheDocument();
  });
});

describe("live incident behaviour", () => {
  /** Starts the incident view for s1 and waits for the list; then switches to fake timers. */
  async function startedOnS1() {
    const user = userEvent.setup();
    const ctx = await mount();
    select("s1");
    await user.click(await screen.findByTestId("show-impact"));
    await waitFor(() => expect(screen.getAllByTestId("impact-row")).toHaveLength(3));
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    return ctx;
  }
  const advance = (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)));

  it("recomputes once, 2 s after a burst of deltas that turn a dependent failing", async () => {
    const { posts, socket } = await startedOnS1();
    expect(posts).toHaveLength(1);
    delta(socket, "a1", "agent", "support-agent", "failing");
    await advance(500);
    delta(socket, "a2", "agent", "triage-agent", "failing");
    await advance(1000);
    expect(posts).toHaveLength(1); // still inside the debounce window
    await advance(1500);
    expect(posts).toHaveLength(2);
    expect(posts[1]?.body).toEqual({ node_id: "s1", max_depth: 2 });
    await advance(5000);
    expect(posts).toHaveLength(2); // exactly once per burst
  });

  it("recomputes when the topology changes", async () => {
    const { posts, socket } = await startedOnS1();
    seq += 1;
    act(() =>
      socket.receive({
        type: "topology",
        domain_id: "d1",
        seq,
        refetch: true,
        truncated: false,
        emitted_at: "t",
        node_ids: [],
        edge_ids: [],
      }),
    );
    await advance(2100);
    expect(posts).toHaveLength(2);
  });

  it("does not recompute for a node that is not part of the incident", async () => {
    const { posts, socket } = await startedOnS1();
    delta(socket, "x1", "agent", "unrelated-agent", "failing");
    await advance(5000);
    expect(posts).toHaveLength(1);
    expect(screen.getByTestId("impact-banner")).toHaveTextContent(
      "unrelated-agent just turned failing",
    );
  });
});

describe("failing nodes outside the incident view", () => {
  it("starts the incident view by itself when the selected node newly turns failing", async () => {
    const { posts, socket } = await mount();
    select("a1");
    await screen.findByTestId("node-panel");
    expect(posts).toHaveLength(0);
    delta(socket, "a1", "agent", "support-agent", "failing");
    await screen.findByTestId("impact-list");
    expect(posts).toHaveLength(1);
    expect(posts[0]?.body).toEqual({ node_id: "a1", max_depth: 2 });
    expect(screen.queryByTestId("impact-banner")).not.toBeInTheDocument();
  });

  it("offers a banner for another node and never starts or moves anything", async () => {
    const user = userEvent.setup();
    const { posts, socket } = await mount();
    select("a1");
    await screen.findByTestId("node-panel");
    delta(socket, "x1", "agent", "unrelated-agent", "failing");
    const banner = await screen.findByTestId("impact-banner");
    expect(banner).toHaveTextContent("unrelated-agent just turned failing");
    expect(posts).toHaveLength(0);
    expect(screen.queryByTestId("impact-list")).not.toBeInTheDocument();
    expect(renderer().centreOn).not.toHaveBeenCalled();
    expect(screen.getByTestId("panel-label")).toHaveTextContent("support-agent"); // selection kept
    await user.click(within(banner).getByRole("button", { name: S.bannerShow }));
    await screen.findByTestId("impact-list");
    expect(posts[0]?.body.node_id).toBe("x1");
    expect(screen.queryByTestId("impact-banner")).not.toBeInTheDocument();
  });

  it("does not restart for a selected node that was already failing", async () => {
    const { posts, socket } = await mount();
    select("a1");
    await screen.findByTestId("node-panel");
    delta(socket, "a1", "agent", "support-agent", "failing");
    await screen.findByTestId("impact-list");
    delta(socket, "a1", "agent", "support-agent", "failing"); // still failing: not a new change
    await act(async () => void (await new Promise((r) => setTimeout(r, 50))));
    expect(posts).toHaveLength(1);
  });
});
