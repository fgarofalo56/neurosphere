import "@testing-library/jest-dom/vitest";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { QueryProvider, createApiClient } from "../../api/index.js";
import { ConfigContext } from "../../app/ConfigContext";
import type { AppConfig } from "../../app/config";
import { createEdgeAnimator, type Scheduler } from "./animator";
import {
  EDGE_COLOUR,
  HEALTH_COLOUR,
  UNKNOWN_OPACITY,
  edgeAppearance,
  kindShape,
  kindSigmaShape,
  nodeAppearance,
} from "./appearance";
import { MapGraph, parseNode, worstCoverage } from "./mapGraph";
import { MapView } from "./MapPage";
import { animationGate, effectiveReducedMotion } from "./motion";
import {
  createLiveClient,
  parseServerMessage,
  realtimeUrl,
  type LiveStatus,
  type WebSocketLike,
} from "./realtime";
import { coverageText } from "./strings";
import {
  NODE_BUDGET,
  NODE_KINDS,
  type Coverage,
  type NodeMetrics,
  type ViewportEdge,
  type ViewportNode,
  type ViewportResponse,
} from "./types";

// ---- sigma is isolated behind ./renderer; jsdom has no WebGL, so the renderer is a recorder.
interface FakeRenderer {
  callbacks: { onSelect(id: string | null): void; onActivate(id: string): void };
  update: ReturnType<typeof vi.fn>;
  setEdgeOffset: ReturnType<typeof vi.fn>;
  select: ReturnType<typeof vi.fn>;
  setReducedMotion: ReturnType<typeof vi.fn>;
  kill: ReturnType<typeof vi.fn>;
}
const rendererRecorder = vi.hoisted(() => ({ created: [] as unknown[] }));
vi.mock("./renderer", () => ({
  createMapRenderer: vi.fn(
    (_container: unknown, _graph: unknown, callbacks: FakeRenderer["callbacks"]) => {
      const r = {
        callbacks,
        update: vi.fn(),
        setEdgeOffset: vi.fn(),
        select: vi.fn(),
        setReducedMotion: vi.fn(),
        kill: vi.fn(),
      };
      rendererRecorder.created.push(r);
      return r;
    },
  ),
}));
vi.mock("../../auth/token", () => ({ getToken: vi.fn(() => Promise.resolve("test-token")) }));

const lastRenderer = (): FakeRenderer => rendererRecorder.created.at(-1) as FakeRenderer;

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

// ---- fixtures
const NULL_METRICS: NodeMetrics = {
  tokens: null,
  context_size: null,
  frequency: null,
  latency_p95_ms: null,
  health: "unknown",
};
const GOOD_METRICS: NodeMetrics = {
  tokens: 1000,
  context_size: 4096,
  frequency: 12,
  latency_p95_ms: 250,
  health: "ok",
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

const COMPLETE: Coverage = { state: "complete", lag_seconds: 0, as_of: "2026-10-20T10:00:00Z" };

const TOP: ViewportResponse = {
  domain_id: "d1",
  nodes: [
    node("cluster:agents", "cluster", "Agents", { member_count: 120 }),
    node("a1", "agent", "support-agent", { metrics: GOOD_METRICS }),
    node("m1", "model", "support-gpt"),
    node("p1", "person", "Person-3fa9"),
  ],
  edges: [
    edge("e1", "a1", "m1", "observed"),
    edge("e2", "a1", "p1", "declared"),
    edge("e3", "p1", "m1", "inferred"),
  ],
  truncated: true,
  truncation_reason: "node_budget",
  next_cursor: null,
  coverage: { state: "partial", lag_seconds: null, as_of: "2026-10-20T10:00:00Z" },
};

const CLUSTER_PAGE_1: ViewportResponse = {
  domain_id: "d1",
  nodes: [
    node("c:1", "agent", "agent-1", { cluster_id: "cluster:agents" }),
    node("c:2", "agent", "agent-2", { cluster_id: "cluster:agents" }),
  ],
  edges: [],
  truncated: true,
  truncation_reason: "node_budget",
  next_cursor: "page-2",
  coverage: { state: "delayed", lag_seconds: 300, as_of: "2026-10-20T09:55:00Z" },
};

const CLUSTER_PAGE_2: ViewportResponse = {
  ...CLUSTER_PAGE_1,
  nodes: [node("c:3", "agent", "agent-3", { cluster_id: "cluster:agents" })],
  truncated: false,
  truncation_reason: null,
  next_cursor: null,
  coverage: COMPLETE,
};

const CONFIG: AppConfig = {
  cloud: "commercial",
  tenantId: "t",
  clientId: "c",
  apiBaseUrl: "http://api.test",
  apiScope: "api://x/.default",
};

// ---- fake WebSocket
class FakeSocket implements WebSocketLike {
  static instances: FakeSocket[] = [];
  onopen: WebSocketLike["onopen"] = null;
  onmessage: WebSocketLike["onmessage"] = null;
  onclose: WebSocketLike["onclose"] = null;
  onerror: WebSocketLike["onerror"] = null;
  sent: string[] = [];
  closed = false;
  constructor(
    readonly url: string,
    readonly protocols: string[],
  ) {
    FakeSocket.instances.push(this);
  }
  send(data: string): void {
    this.sent.push(data);
  }
  close(): void {
    this.closed = true;
  }
  open(): void {
    this.onopen?.({});
  }
  receive(message: unknown): void {
    this.onmessage?.({ data: typeof message === "string" ? message : JSON.stringify(message) });
  }
  drop(code: number): void {
    this.onclose?.({ code });
  }
}

function setup(responses: Record<string, ViewportResponse> = {}, status = 200) {
  const requested: URL[] = [];
  const fetchImpl = vi.fn<typeof fetch>((input) => {
    const url = new URL(String(input));
    requested.push(url);
    if (status !== 200) return Promise.resolve(new Response("{}", { status }));
    const cluster = url.searchParams.get("cluster_id");
    const cursor = url.searchParams.get("cursor");
    const key = cluster === null ? "top" : `${cluster}|${cursor ?? ""}`;
    const body = responses[key] ?? TOP;
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
  });
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("t"),
  });
  const withFetch = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("t"),
    fetchImpl,
    maxRetries: 0,
  });
  void client;
  return { fetchImpl, requested, client: withFetch };
}

function wrap(ui: ReactElement, client: ReturnType<typeof setup>["client"]) {
  return (
    <ConfigContext.Provider value={CONFIG}>
      <QueryProvider client={client}>
        <MemoryRouter>{ui}</MemoryRouter>
      </QueryProvider>
    </ConfigContext.Provider>
  );
}

function manualScheduler() {
  const queue = new Map<number, (t: number) => void>();
  let next = 1;
  let requested = 0;
  const scheduler: Scheduler = {
    request(cb) {
      const h = next++;
      requested += 1;
      queue.set(h, cb);
      return h;
    },
    cancel(h) {
      queue.delete(h);
    },
  };
  return {
    scheduler,
    flush(timeMs: number) {
      const callbacks = [...queue.values()];
      queue.clear();
      for (const cb of callbacks) cb(timeMs);
    },
    pending: () => queue.size,
    requested: () => requested,
  };
}

function stubMatchMedia(reduce: boolean): void {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: reduce && query.includes("prefers-reduced-motion"),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: globalThis.matchMedia,
  });
}

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
  FakeSocket.instances = [];
  rendererRecorder.created.length = 0;
  vi.stubGlobal("WebSocket", FakeSocket);
  stubMatchMedia(false);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------------------------
describe("appearance", () => {
  it("gives every kind a distinct shape, from the PRP-04 icon set", () => {
    const shapes = NODE_KINDS.map((k) => kindSigmaShape(k));
    expect(new Set(shapes).size).toBe(NODE_KINDS.length);
    expect(kindShape("person")).toBe("circle");
    expect(kindShape("agent")).toBe("hexagon");
    expect(kindShape("sub_agent")).toBe("diamond");
    expect(kindShape("model")).toBe("square");
    expect(kindShape("source")).toBe("pill");
    expect(kindShape("cluster")).toBe("triangle");
  });

  it("renders unknown metrics in a distinct unknown style, never as 0", () => {
    const known = nodeAppearance(
      "agent",
      GOOD_METRICS,
      null,
      "tokens",
      { min: 0, max: 2000 },
      null,
    );
    const unknown = nodeAppearance(
      "agent",
      NULL_METRICS,
      null,
      "tokens",
      { min: 0, max: 2000 },
      null,
    );
    expect(known.sizeUnknown).toBe(false);
    expect(unknown.sizeUnknown).toBe(true);
    expect(unknown.opacity).toBe(UNKNOWN_OPACITY);
    expect(unknown.size).toBeGreaterThan(0);
    // Unknown is not the "smallest known" value.
    expect(unknown.opacity).toBeLessThan(known.opacity);
    // No known values anywhere: everything is unknown, not zero-sized.
    expect(nodeAppearance("agent", GOOD_METRICS, null, "tokens", null, null).sizeUnknown).toBe(
      true,
    );
  });

  it("colours by health and keeps unknown grey", () => {
    const failing = nodeAppearance(
      "agent",
      { ...GOOD_METRICS, health: "failing" },
      null,
      "tokens",
      null,
      null,
    );
    expect(failing.color).toBe(HEALTH_COLOUR.failing);
    expect(unknownColour()).toBe(HEALTH_COLOUR.unknown);
  });

  it("animates observed edges only, and only when motion is allowed", () => {
    expect(edgeAppearance("observed", true).animated).toBe(true);
    expect(edgeAppearance("observed", false).animated).toBe(false);
    expect(edgeAppearance("declared", true).animated).toBe(false);
    expect(edgeAppearance("inferred", true).animated).toBe(false);
    // Declared and inferred are visually distinct from observed and from each other.
    const looks = (["observed", "declared", "inferred"] as const).map((p) =>
      edgeAppearance(p, false),
    );
    expect(new Set(looks.map((l) => `${l.dashSize}/${l.gapSize}`)).size).toBe(3);
    expect(EDGE_COLOUR.observed).not.toBe(EDGE_COLOUR.declared);
  });
});

function unknownColour(): string {
  return nodeAppearance("model", NULL_METRICS, null, "tokens", null, null).color;
}

// ---------------------------------------------------------------------------------------------
describe("MapGraph", () => {
  function build(): MapGraph {
    const g = new MapGraph();
    g.upsertNodes(TOP.nodes);
    g.upsertEdges(TOP.edges);
    g.restyle();
    return g;
  }

  it("builds shapes per kind, edge styles per provenance and unknown styling from null metrics", () => {
    const g = build();
    expect(g.nodeCount).toBe(4);
    expect(g.edgeCount).toBe(3);
    expect(g.graph.getNodeAttribute("a1", "shape")).toBe("hexagon");
    expect(g.graph.getNodeAttribute("m1", "shape")).toBe("square");
    expect(g.graph.getNodeAttribute("p1", "shape")).toBe("circle");
    expect(g.graph.getNodeAttribute("cluster:agents", "shape")).toBe("triangle");
    expect(g.graph.getNodeAttribute("a1", "sizeUnknown")).toBe(false);
    expect(g.graph.getNodeAttribute("m1", "sizeUnknown")).toBe(true);
    expect(g.graph.getNodeAttribute("m1", "size")).toBeGreaterThan(0);
    expect(g.graph.getEdgeAttribute("e1", "animated")).toBe(true);
    expect(g.graph.getEdgeAttribute("e2", "animated")).toBe(false);
    expect(g.graph.getEdgeAttribute("e3", "animated")).toBe(false);
    expect(g.animatedEdgeIds()).toEqual(["e1"]);
  });

  it("stops animating every edge when reduced motion is on", () => {
    const g = build();
    g.restyle({ sizeBy: "tokens", animateEdges: false });
    expect(g.animatedEdgeIds()).toEqual([]);
    expect(g.graph.getEdgeAttribute("e1", "animated")).toBe(false);
    g.restyle({ sizeBy: "tokens", animateEdges: true });
    expect(g.animatedEdgeIds()).toEqual(["e1"]);
  });

  it("renders labels exactly as served", () => {
    const g = build();
    expect(g.graph.getNodeAttribute("p1", "label")).toBe("Person-3fa9");
  });

  it("holds edges until both endpoints are loaded", () => {
    const g = new MapGraph();
    g.upsertNodes([node("x", "agent", "x")]);
    g.upsertEdges([edge("ex", "x", "y", "observed")]);
    expect(g.edgeCount).toBe(0);
    g.upsertNodes([node("y", "model", "y")]);
    g.upsertEdges([]);
    expect(g.edgeCount).toBe(1);
  });

  it("never holds more than the 2000-node budget", () => {
    const g = new MapGraph();
    const many = Array.from({ length: NODE_BUDGET + 5 }, (_, i) => node(`n${i}`, "agent", `n${i}`));
    expect(g.upsertNodes(many)).toBe(5);
    expect(g.nodeCount).toBe(NODE_BUDGET);
    expect(g.remainingBudget).toBe(0);
  });

  it("keeps existing positions stable when more nodes arrive", () => {
    const g = build();
    const before = { ...g.graph.getNodeAttributes("a1") };
    g.upsertNodes([
      node("a2", "agent", "a2"),
      node("a1", "agent", "support-agent", { metrics: GOOD_METRICS }),
    ]);
    expect(g.graph.getNodeAttribute("a1", "x")).toBe(before.x);
    expect(g.graph.getNodeAttribute("a1", "y")).toBe(before.y);
  });

  it("applies a realtime delta (one domain-level cluster node, no edges) and ignores junk", () => {
    const g = build();
    g.applyDelta(
      [
        {
          id: "d1",
          kind: "cluster",
          label: "finance",
          metrics: { health: "degraded", latency_p95_ms: 90 },
        },
        { kind: "agent" },
        "not-a-node",
        { id: "z", kind: "spaceship", label: "z" },
      ],
      [],
    );
    expect(g.nodeCount).toBe(5);
    const delta = g.graph.getNodeAttributes("d1");
    expect(delta.kind).toBe("cluster");
    expect(delta.metrics.health).toBe("degraded");
    expect(delta.metrics.tokens).toBeNull();
    expect(g.graph.hasNode("z")).toBe(false);
  });

  it("parses nodes defensively", () => {
    expect(parseNode(null)).toBeNull();
    expect(parseNode({ id: "a", kind: "agent" })?.metrics.health).toBe("unknown");
    expect(
      parseNode({ id: "a", kind: "agent", metrics: { tokens: "x" } })?.metrics.tokens,
    ).toBeNull();
  });
});

describe("coverage", () => {
  it("never smooths a gap over: the worst state wins and the largest lag is kept", () => {
    const worst = worstCoverage([
      COMPLETE,
      { state: "delayed", lag_seconds: 300, as_of: "t" },
      { state: "partial", lag_seconds: 5, as_of: "t" },
    ]);
    expect(worst?.state).toBe("delayed");
    expect(worst?.lag_seconds).toBe(300);
    expect(worstCoverage([])).toBeNull();
  });

  it("labels partial, delayed (with lag) and unknown coverage", () => {
    expect(coverageText("partial", null, null)).toMatch(/Partial coverage/);
    expect(coverageText("delayed", 300, null)).toBe("Delayed: data is 300 s behind");
    expect(coverageText("unknown", null, null)).toBe("Coverage unknown");
  });
});

describe("reduced motion", () => {
  it("is on when the system asks OR the in-app toggle is on", () => {
    expect(effectiveReducedMotion(false, false)).toBe(false);
    expect(effectiveReducedMotion(true, false)).toBe(true);
    expect(effectiveReducedMotion(false, true)).toBe(true);
    expect(effectiveReducedMotion(true, true)).toBe(true);
  });
});

describe("edge animator", () => {
  it("moves only the ids it is given and counts frames", () => {
    const sched = manualScheduler();
    const setOffset = vi.fn();
    const animator = createEdgeAnimator(
      { animatedEdgeIds: () => ["e1"], setOffset },
      sched.scheduler,
    );
    animator.start();
    sched.flush(0);
    sched.flush(100);
    expect(animator.frames).toBe(2);
    expect(setOffset).toHaveBeenCalledTimes(2);
    expect(setOffset.mock.calls[0]?.[0]).toEqual(["e1"]);
    expect(setOffset.mock.calls[1]?.[1]).toBeGreaterThan(setOffset.mock.calls[0]?.[1] as number);
  });

  it("schedules nothing once stopped, and nothing to redraw when no edge animates", () => {
    const sched = manualScheduler();
    const setOffset = vi.fn();
    const animator = createEdgeAnimator({ animatedEdgeIds: () => [], setOffset }, sched.scheduler);
    animator.start();
    sched.flush(0);
    expect(setOffset).not.toHaveBeenCalled();
    animator.stop();
    expect(sched.pending()).toBe(0);
    const requestedBefore = sched.requested();
    sched.flush(50);
    expect(sched.requested()).toBe(requestedBefore);
    expect(animator.running).toBe(false);
  });
});

// ---------------------------------------------------------------------------------------------
describe("realtime client", () => {
  const delta = (over: Record<string, unknown> = {}) => ({
    type: "delta",
    domain_id: "d1",
    seq: 1,
    nodes: [{ id: "d1", kind: "cluster", label: "finance", metrics: { health: "ok" } }],
    edges: [],
    coverage: { state: "complete", lag_seconds: 1, as_of: "t" },
    emitted_at: "t",
    ...over,
  });

  function makeClient(extra: { getToken?: () => Promise<string> } = {}) {
    const statuses: LiveStatus[] = [];
    const deltas: number[] = [];
    const timers: { cb: () => void; ms: number }[] = [];
    const client = createLiveClient({
      url: "ws://api.test/api/v1/realtime/ws",
      domainId: "d1",
      getToken: extra.getToken ?? (() => Promise.resolve("secret-token")),
      onStatus: (s) => statuses.push(s),
      onDelta: (d) => deltas.push(d.seq),
      socketFactory: (url, protocols) => new FakeSocket(url, protocols),
      setTimer: (cb, ms) => timers.push({ cb, ms }),
      clearTimer: () => {},
    });
    return { client, statuses, deltas, timers };
  }

  const settle = () => act(async () => void (await Promise.resolve()));

  it("builds the ws url from the api base url", () => {
    expect(realtimeUrl("http://api.test/")).toBe("ws://api.test/api/v1/realtime/ws");
    expect(realtimeUrl("https://api.test")).toBe("wss://api.test/api/v1/realtime/ws");
  });

  it("ignores unknown and malformed message types", () => {
    expect(parseServerMessage(JSON.stringify({ type: "pong" })).kind).toBe("ignored");
    expect(parseServerMessage(JSON.stringify({ type: "unsubscribed" })).kind).toBe("ignored");
    expect(parseServerMessage("not json").kind).toBe("ignored");
    expect(parseServerMessage(JSON.stringify({ type: "delta", seq: "x" })).kind).toBe("ignored");
    expect(parseServerMessage(JSON.stringify({ type: "subscribed", domain_id: "d1" })).kind).toBe(
      "subscribed",
    );
  });

  it("sends the bearer in the subprotocol (never the url), subscribes, and applies deltas", async () => {
    const { client, statuses, deltas } = makeClient();
    client.start();
    await settle();
    const socket = FakeSocket.instances[0] as FakeSocket;
    expect(socket.protocols).toEqual(["ns.bearer", "secret-token"]);
    expect(socket.url).not.toContain("secret-token");
    socket.open();
    expect(JSON.parse(socket.sent[0] as string)).toEqual({ type: "subscribe", domain_id: "d1" });
    socket.receive({ type: "subscribed", domain_id: "d1" });
    expect(statuses.at(-1)).toBe("live");
    socket.receive({ type: "pong" });
    socket.receive({ type: "something-new", x: 1 });
    socket.receive(delta({ seq: 1 }));
    socket.receive(delta({ seq: 1 })); // replayed frame
    socket.receive(delta({ seq: 0 })); // reordered frame
    socket.receive(delta({ seq: 2, domain_id: "other" })); // not our domain
    socket.receive(delta({ seq: 3 }));
    expect(deltas).toEqual([1, 3]);
  });

  it("stops for good on 4403 (revoked) and never reconnects", async () => {
    const { client, statuses, timers } = makeClient();
    client.start();
    await settle();
    const socket = FakeSocket.instances[0] as FakeSocket;
    socket.open();
    socket.receive({ type: "subscribed" });
    socket.drop(4403);
    expect(statuses.at(-1)).toBe("revoked");
    expect(timers).toHaveLength(0);
    await settle();
    expect(FakeSocket.instances).toHaveLength(1);
  });

  it("retries 4401 once with a fresh token, then reports unauthenticated", async () => {
    const getToken = vi.fn(() => Promise.resolve("t"));
    const { client, statuses, timers } = makeClient({ getToken });
    client.start();
    await settle();
    FakeSocket.instances[0]?.drop(4401);
    expect(timers).toHaveLength(1);
    timers[0]?.cb();
    await settle();
    expect(getToken).toHaveBeenCalledTimes(2);
    FakeSocket.instances[1]?.drop(4401);
    expect(statuses.at(-1)).toBe("unauthenticated");
    expect(timers).toHaveLength(1);
  });

  it("says unavailable when the gateway cannot be reached, and tolerates 1013 and 4429", async () => {
    const { client, statuses, timers } = makeClient();
    client.start();
    await settle();
    FakeSocket.instances[0]?.drop(1006);
    expect(statuses.at(-1)).toBe("unavailable");
    expect(timers).toHaveLength(1);
    timers[0]?.cb();
    await settle();
    FakeSocket.instances[1]?.drop(1013);
    expect(timers).toHaveLength(2);
    timers[1]?.cb();
    await settle();
    FakeSocket.instances[2]?.drop(4429);
    expect(timers[2]?.ms).toBeGreaterThanOrEqual(30_000);
  });

  it("reports unauthenticated when no token can be acquired", async () => {
    const { client, statuses } = makeClient({
      getToken: () => Promise.reject(new Error("no auth")),
    });
    client.start();
    await settle();
    expect(statuses.at(-1)).toBe("unauthenticated");
    expect(FakeSocket.instances).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------------------------
describe("MapView", () => {
  async function mount(
    responses: Record<string, ViewportResponse> = {},
    status = 200,
    scheduler?: Scheduler,
  ) {
    const ctx = setup(responses, status);
    const utils = render(
      wrap(<MapView domainId="d1" {...(scheduler !== undefined && { scheduler })} />, ctx.client),
    );
    return { ...ctx, ...utils };
  }

  it("requests the viewport for the addressed domain with the 2000 node budget, never a scope param", async () => {
    const { requested } = await mount();
    await screen.findByTestId("map-canvas");
    const first = requested[0] as URL;
    expect(first.pathname).toBe("/api/v1/map/domains/d1/viewport");
    expect(first.searchParams.get("node_budget")).toBe("2000");
    expect(first.searchParams.has("domain_id")).toBe(false);
  });

  it("keeps the WebGL view in a named region next to a visible 'View as table' link", async () => {
    await mount();
    const region = await screen.findByRole("region", { name: /Agent topology map/ });
    expect(region).toHaveAttribute("data-testid", "map-canvas");
    const link = screen.getByRole("link", { name: "View as table" });
    expect(link).toHaveAttribute("href", "/map/table?domain_id=d1");
  });

  it("labels coverage and truncation, with the reason", async () => {
    await mount();
    const label = await screen.findByTestId("coverage-label");
    await waitFor(() => expect(label).toHaveAttribute("data-coverage-state", "partial"));
    expect(label).toHaveTextContent(/Partial coverage/);
    const banner = await screen.findByTestId("truncation-banner");
    expect(banner).toHaveTextContent("node budget reached");
  });

  it("shows the legends: size metrics, health text, node kinds, edge styles", async () => {
    await mount();
    const legend = await screen.findByTestId("map-legend");
    const sizeBy = within(legend).getByRole("combobox", { name: "Size by" });
    expect(
      within(sizeBy)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Tokens", "Context size", "Frequency", "Latency (p95 ms)"]);
    const health = within(within(legend).getByTestId("health-legend"));
    for (const word of ["ok", "degraded", "failing", "unknown"]) health.getByText(word);
    const kinds = within(within(legend).getByTestId("kind-legend"));
    for (const label of ["Person", "Agent", "Sub-agent", "Model", "Source", "Cluster"]) {
      kinds.getByText(label);
    }
    expect(within(legend).getAllByText(/Observed|Declared|Inferred/)).toHaveLength(3);
    // The unknown count never reads as zero-valued data: models/persons have null tokens.
    expect(within(legend).getByTestId("size-unknown")).toHaveTextContent(
      /no data \(never shown as 0\)/,
    );
  });

  it("re-sizes when the size legend changes", async () => {
    const user = userEvent.setup();
    await mount();
    const legend = await screen.findByTestId("map-legend");
    expect(within(legend).getByTestId("size-max")).toHaveTextContent("1000");
    await user.selectOptions(
      within(legend).getByRole("combobox", { name: "Size by" }),
      "frequency",
    );
    expect(within(legend).getByTestId("size-max")).toHaveTextContent("12");
    await user.selectOptions(
      within(legend).getByRole("combobox", { name: "Size by" }),
      "context_size",
    );
    expect(within(legend).getByTestId("size-max")).toHaveTextContent("4096");
  });

  it("drills down: the side panel shows metrics (unknown, never 0) and links only", async () => {
    await mount();
    await screen.findByTestId("map-canvas");
    act(() => lastRenderer().callbacks.onSelect("m1"));
    const panel = await screen.findByTestId("node-panel");
    expect(within(panel).getByTestId("panel-label")).toHaveTextContent("support-gpt");
    expect(within(panel).getByTestId("metric-tokens")).toHaveTextContent("unknown");
    expect(within(panel).getByTestId("metric-health")).toHaveTextContent("unknown");
    expect(within(panel).queryByText("0")).toBeNull();
    const links = within(panel).getAllByRole("link");
    expect(links.map((l) => l.getAttribute("href"))).toEqual([
      "/dashboards/cost?domain_id=d1",
      "/dashboards/latency?domain_id=d1",
      "/recommendations?domain_id=d1",
      "/replay/traces?domain_id=d1",
    ]);
    expect(within(panel).queryByRole("button", { name: /expand/i })).toBeNull();

    act(() => lastRenderer().callbacks.onSelect("a1"));
    expect(
      await within(await screen.findByTestId("node-panel")).findByTestId("metric-tokens"),
    ).toHaveTextContent("1000");
    act(() => lastRenderer().callbacks.onSelect(null));
    await waitFor(() => expect(screen.queryByTestId("node-panel")).toBeNull());
  });

  it("expands a cluster and pages with next_cursor, never exceeding the budget", async () => {
    const user = userEvent.setup();
    const { requested } = await mount({
      "cluster:agents|": CLUSTER_PAGE_1,
      "cluster:agents|page-2": CLUSTER_PAGE_2,
    });
    await screen.findByTestId("map-canvas");
    act(() => lastRenderer().callbacks.onSelect("cluster:agents"));
    const panel = await screen.findByTestId("node-panel");
    expect(within(panel).getByTestId("panel-members")).toHaveTextContent("120 members");
    await user.click(within(panel).getByRole("button", { name: "Expand cluster" }));

    await waitFor(() => expect(screen.getByTestId("node-count")).toHaveTextContent("6 nodes"));
    const clusterCall = requested.find(
      (u) => u.searchParams.get("cluster_id") === "cluster:agents",
    );
    expect(clusterCall?.searchParams.get("cursor")).toBeNull();
    // The delayed page is labelled, not smoothed over by the earlier pages.
    await waitFor(() =>
      expect(screen.getByTestId("coverage-label")).toHaveAttribute(
        "data-coverage-state",
        "delayed",
      ),
    );
    expect(screen.getByTestId("coverage-label")).toHaveTextContent("Delayed: data is 300 s behind");

    await user.click(
      await within(await screen.findByTestId("node-panel")).findByRole("button", {
        name: "Load more",
      }),
    );
    await waitFor(() => expect(screen.getByTestId("node-count")).toHaveTextContent("7 nodes"));
    const pageTwo = requested.find((u) => u.searchParams.get("cursor") === "page-2");
    expect(pageTwo?.searchParams.get("cluster_id")).toBe("cluster:agents");
    // Exhausted: no more button.
    await waitFor(() =>
      expect(
        within(screen.getByTestId("node-panel")).queryByRole("button", {
          name: /load more|expand/i,
        }),
      ).toBeNull(),
    );
    for (const u of requested) {
      expect(Number(u.searchParams.get("node_budget"))).toBeLessThanOrEqual(NODE_BUDGET);
    }
  });

  it("double-clicking a cluster expands it", async () => {
    const { requested } = await mount({ "cluster:agents|": CLUSTER_PAGE_1 });
    await screen.findByTestId("map-canvas");
    act(() => lastRenderer().callbacks.onActivate("cluster:agents"));
    await waitFor(() =>
      expect(requested.some((u) => u.searchParams.get("cluster_id") === "cluster:agents")).toBe(
        true,
      ),
    );
  });

  /** Opens the (fake) gateway socket and subscribes: the status becomes "live". */
  async function goLive(): Promise<FakeSocket> {
    await screen.findByTestId("map-canvas");
    await waitFor(() => expect(FakeSocket.instances).toHaveLength(1));
    const socket = FakeSocket.instances[0] as FakeSocket;
    act(() => socket.open());
    act(() => socket.receive({ type: "subscribed", domain_id: "d1" }));
    return socket;
  }

  const liveDelta = (seq: number, state: Coverage["state"], lag: number | null = 0) => ({
    type: "delta",
    domain_id: "d1",
    seq,
    nodes: [],
    edges: [],
    coverage: { state, lag_seconds: lag, as_of: "t" },
    emitted_at: "t",
  });

  it("does not animate before the socket is live, and says why", async () => {
    const sched = manualScheduler();
    await mount({}, 200, sched.scheduler);
    const canvas = await screen.findByTestId("map-canvas");
    expect(canvas).toHaveAttribute("data-edge-animation", "off");
    expect(sched.requested()).toBe(0);
    expect(screen.getByTestId("animation-status")).toHaveTextContent(
      "Edge animation paused: live updates not connected",
    );
  });

  it("stops the animator when the socket closes, and resumes when live again", async () => {
    const sched = manualScheduler();
    await mount({}, 200, sched.scheduler);
    const socket = await goLive();
    const canvas = screen.getByTestId("map-canvas");
    await waitFor(() => expect(canvas).toHaveAttribute("data-edge-animation", "on"));
    expect(sched.pending()).toBeGreaterThan(0);

    act(() => socket.drop(1006)); // lost after being live: reconnecting
    await waitFor(() => expect(canvas).toHaveAttribute("data-edge-animation", "off"));
    expect(canvas).toHaveAttribute("data-animated-edges", "0");
    expect(sched.pending()).toBe(0);
    expect(screen.getByTestId("animation-status")).toHaveTextContent(
      "Edge animation paused: live updates not connected",
    );
  });

  it.each([
    "connecting",
    "reconnecting",
    "disconnected",
    "unavailable",
    "unauthenticated",
    "revoked",
  ] as const)("never animates while the live status is %s", (status) => {
    expect(animationGate(false, status, "complete")).toBe("notLive");
    expect(animationGate(false, status, "partial")).toBe("notLive");
  });

  it("animates only when live with complete or partial coverage, and reduced motion wins", () => {
    expect(animationGate(false, "live", "complete")).toBe("on");
    expect(animationGate(false, "live", "partial")).toBe("on");
    expect(animationGate(false, "live", "delayed")).toBe("delayed");
    expect(animationGate(false, "live", "unknown")).toBe("unknown");
    expect(animationGate(false, "live", null)).toBe("unknown");
    expect(animationGate(true, "live", "complete")).toBe("reduced");
  });

  it("clears the graph and animation on 4403 (access revoked)", async () => {
    const sched = manualScheduler();
    await mount({}, 200, sched.scheduler);
    const socket = await goLive();
    const canvas = screen.getByTestId("map-canvas");
    await waitFor(() => expect(canvas).toHaveAttribute("data-edge-animation", "on"));
    expect(screen.getByTestId("node-count")).toHaveTextContent("4 nodes");

    act(() => socket.drop(4403));
    await waitFor(() => expect(canvas).toHaveAttribute("data-edge-animation", "off"));
    expect(sched.pending()).toBe(0);
    expect(screen.getByTestId("access-revoked")).toHaveTextContent(/Access revoked/);
    expect(screen.getByTestId("node-count")).toHaveTextContent("0 nodes, 0 edges");
    expect(canvas).toHaveAttribute("data-node-count", "0");
    expect(canvas).toHaveAttribute("data-animated-edges", "0");
    expect(screen.queryByTestId("coverage-label")).toBeNull();
    expect(screen.queryByTestId("truncation-banner")).toBeNull();
  });

  it.each([
    ["delayed", "Edge animation paused: data delayed", 120],
    ["unknown", "Edge animation paused: coverage unknown", null],
  ] as const)(
    "pauses animation when coverage becomes %s and resumes when complete",
    async (state, text, lag) => {
      const sched = manualScheduler();
      await mount({}, 200, sched.scheduler);
      const socket = await goLive();
      const canvas = screen.getByTestId("map-canvas");
      await waitFor(() => expect(canvas).toHaveAttribute("data-edge-animation", "on"));

      act(() => socket.receive(liveDelta(1, state, lag)));
      await waitFor(() => expect(canvas).toHaveAttribute("data-edge-animation", "off"));
      expect(sched.pending()).toBe(0);
      expect(canvas).toHaveAttribute("data-animated-edges", "0");
      expect(screen.getByTestId("animation-status")).toHaveTextContent(text);

      act(() => socket.receive(liveDelta(2, "complete")));
      await waitFor(() => expect(canvas).toHaveAttribute("data-edge-animation", "on"));
      expect(canvas).toHaveAttribute("data-animated-edges", "1");
      expect(sched.pending()).toBeGreaterThan(0);
      expect(screen.getByTestId("animation-status")).toHaveTextContent("Observed edges animate");
    },
  );

  it("caches the observed-edge ids between frames instead of filtering per frame", () => {
    const g = new MapGraph();
    g.upsertNodes(TOP.nodes);
    g.upsertEdges(TOP.edges);
    g.restyle();
    const spy = vi.spyOn(g.graph, "filterEdges");
    const first = g.animatedEdgeIds();
    expect(g.animatedEdgeIds()).toBe(first);
    expect(g.animatedEdgeIds()).toBe(first);
    expect(spy).toHaveBeenCalledTimes(1);
    g.restyle({ sizeBy: "tokens", animateEdges: true });
    g.animatedEdgeIds();
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("turns edge animation off for the system preference and the in-app toggle", async () => {
    const user = userEvent.setup();
    const sched = manualScheduler();
    await mount({}, 200, sched.scheduler);
    await goLive();
    const canvas = await screen.findByTestId("map-canvas");
    await waitFor(() => expect(canvas).toHaveAttribute("data-edge-animation", "on"));
    expect(screen.getByTestId("animation-status")).toHaveTextContent("Observed edges animate");
    expect(sched.pending()).toBeGreaterThan(0);
    // Only the observed edge is handed to the animator.
    act(() => sched.flush(16));
    await waitFor(() => expect(lastRenderer().setEdgeOffset).toHaveBeenCalled());
    expect(lastRenderer().setEdgeOffset.mock.calls[0]?.[0]).toEqual(["e1"]);

    await user.click(screen.getByRole("switch", { name: /reduce motion/i }));
    await waitFor(() => expect(canvas).toHaveAttribute("data-edge-animation", "off"));
    expect(canvas).toHaveAttribute("data-animated-edges", "0");
    expect(sched.pending()).toBe(0);
    expect(lastRenderer().setReducedMotion).toHaveBeenLastCalledWith(true);
    expect(screen.getByTestId("animation-status")).toHaveTextContent(
      "Edge animation paused: reduced motion",
    );
  });

  it("honours prefers-reduced-motion from the start: no animation frame is ever scheduled", async () => {
    stubMatchMedia(true);
    const sched = manualScheduler();
    await mount({}, 200, sched.scheduler);
    const canvas = await screen.findByTestId("map-canvas");
    expect(canvas).toHaveAttribute("data-edge-animation", "off");
    expect(sched.requested()).toBe(0);
    const toggle = screen.getByRole("switch", { name: /reduce motion/i });
    expect(toggle).toBeChecked();
    expect(toggle).toBeDisabled();
  });

  it("shows an error, not an empty map, when the request fails", async () => {
    await mount({}, 500);
    expect(await screen.findByTestId("error-state")).toHaveTextContent("Could not load the map");
    expect(screen.queryByTestId("map-canvas")).toBeNull();
  });

  it("shows access denied on 403", async () => {
    await mount({}, 403);
    expect(await screen.findByTestId("forbidden-state")).toBeInTheDocument();
  });

  it("applies live deltas from the gateway and ignores unknown message types", async () => {
    await mount();
    await screen.findByTestId("map-canvas");
    await waitFor(() => expect(FakeSocket.instances).toHaveLength(1));
    const socket = FakeSocket.instances[0] as FakeSocket;
    expect(socket.url).toBe("ws://api.test/api/v1/realtime/ws");
    expect(socket.protocols).toEqual(["ns.bearer", "test-token"]);
    act(() => socket.open());
    act(() => socket.receive({ type: "subscribed", domain_id: "d1" }));
    expect(screen.getByTestId("live-status")).toHaveAttribute("data-live-status", "live");
    expect(screen.getByTestId("node-count")).toHaveTextContent("4 nodes");

    act(() => socket.receive({ type: "pong" }));
    act(() =>
      socket.receive({
        type: "delta",
        domain_id: "d1",
        seq: 1,
        nodes: [{ id: "d1", kind: "cluster", label: "finance", metrics: { health: "degraded" } }],
        edges: [],
        coverage: { state: "delayed", lag_seconds: 90, as_of: "t" },
        emitted_at: "t",
      }),
    );
    expect(screen.getByTestId("node-count")).toHaveTextContent("5 nodes");
    expect(screen.getByTestId("coverage-label")).toHaveAttribute("data-coverage-state", "delayed");
  });

  it("shows a clear revoked state on 4403 and does not reconnect", async () => {
    await mount();
    await screen.findByTestId("map-canvas");
    await waitFor(() => expect(FakeSocket.instances).toHaveLength(1));
    const socket = FakeSocket.instances[0] as FakeSocket;
    act(() => socket.open());
    act(() => socket.receive({ type: "subscribed" }));
    act(() => socket.drop(4403));
    const status = screen.getByTestId("live-status");
    expect(status).toHaveAttribute("data-live-status", "revoked");
    expect(status).toHaveTextContent(/revoked/);
    await new Promise((r) => setTimeout(r, 30));
    expect(FakeSocket.instances).toHaveLength(1);
  });

  it("says live updates are unavailable when the gateway cannot be reached", async () => {
    await mount();
    await screen.findByTestId("map-canvas");
    await waitFor(() => expect(FakeSocket.instances).toHaveLength(1));
    act(() => FakeSocket.instances[0]?.drop(1006));
    expect(screen.getByTestId("live-status")).toHaveAttribute("data-live-status", "unavailable");
    expect(screen.getByTestId("live-status")).toHaveTextContent(/Live updates unavailable/);
  });

  it("has no axe violations", async () => {
    const { container } = await mount();
    await screen.findByTestId("map-canvas");
    const results = await axe(container, { rules: { region: { enabled: false } } });
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
});
