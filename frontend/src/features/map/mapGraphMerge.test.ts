import { describe, expect, it } from "vitest";
import { MapGraph } from "./mapGraph";
import { NODE_BUDGET, type ViewportEdge, type ViewportNode } from "./types";

const METRICS = {
  tokens: null,
  context_size: null,
  frequency: null,
  latency_p95_ms: null,
  health: "ok",
} as const;

function node(id: string, over: Partial<ViewportNode> = {}): ViewportNode {
  return {
    id,
    kind: "agent",
    label: id,
    cluster_id: null,
    member_count: null,
    metrics: METRICS,
    ...over,
  };
}

function edge(id: string, source: string, target: string): ViewportEdge {
  return { id, source, target, provenance: "observed", last_observed_at: null };
}

function fill(count: number): MapGraph {
  const g = new MapGraph();
  g.upsertNodes(Array.from({ length: count }, (_, i) => node(`n${i}`)));
  return g;
}

describe("MapGraph.mergeNeighbourhood", () => {
  it("keeps cluster_id and does not drift the cluster placement (viewport and neighbourhood paths)", () => {
    const g = new MapGraph();
    g.upsertNodes([
      node("c1", { kind: "cluster", member_count: 5 }),
      node("v1", { cluster_id: "c1" }),
    ]);
    const result = g.mergeNeighbourhood(
      "x1",
      [node("x1", { cluster_id: "c1" }), node("c1", { kind: "cluster", member_count: 5 })],
      [edge("e1", "x1", "c1")],
    );
    expect(result).toMatchObject({ added: 1, dropped: 0, skipped: 0, centred: true });
    expect(g.graph.getNodeAttribute("v1", "clusterId")).toBe("c1");
    expect(g.graph.getNodeAttribute("x1", "clusterId")).toBe("c1");
    const inCluster = g.graph.filterNodes((_, a) => a.clusterId === "c1");
    expect(inCluster.sort()).toEqual(["v1", "x1"]);
    // Both members sit around the cluster, not on the top-level disc.
    const c = g.graph.getNodeAttributes("c1");
    for (const id of inCluster) {
      const a = g.graph.getNodeAttributes(id);
      expect(Math.hypot(a.x - c.x, a.y - c.y)).toBeLessThan(400);
    }
  });

  it("adds edges between merged and existing nodes", () => {
    const g = fill(3);
    g.mergeNeighbourhood("far", [node("far"), node("n0")], [edge("e1", "far", "n0")]);
    expect(g.graph.hasEdge("e1")).toBe(true);
  });

  it("never exceeds the 2000-node cap", () => {
    const g = fill(NODE_BUDGET);
    const incoming = [node("centre"), ...Array.from({ length: 30 }, (_, i) => node(`new${i}`))];
    const result = g.mergeNeighbourhood("centre", incoming, []);
    expect(g.nodeCount).toBeLessThanOrEqual(NODE_BUDGET);
    expect(g.graph.hasNode("centre")).toBe(true);
    expect(result.dropped).toBe(31);
    expect(result.added).toBe(31);
    expect(result.skipped).toBe(0);
  });

  it("drops the farthest unselected leaves first", () => {
    const g = fill(NODE_BUDGET);
    // Anchor the neighbourhood at n0 (an existing node the response links to).
    const anchor = g.graph.getNodeAttributes("n0");
    const ranked = g.graph
      .mapNodes((id, a) => ({ id, d: Math.hypot(a.x - anchor.x, a.y - anchor.y) }))
      .filter((n) => n.id !== "n0")
      .sort((a, b) => b.d - a.d);
    const farthest = ranked.slice(0, 2).map((n) => n.id);
    const nearest = ranked.at(-1)?.id as string;
    g.mergeNeighbourhood(
      "centre",
      [node("centre"), node("n0")],
      [edge("e1", "centre", "n0"), edge("e2", "n0", "n0")],
    );
    // One slot needed for "centre" -> exactly the single farthest leaf goes.
    expect(g.graph.hasNode(farthest[0] as string)).toBe(false);
    expect(g.graph.hasNode(farthest[1] as string)).toBe(true);
    expect(g.graph.hasNode(nearest)).toBe(true);
    expect(g.nodeCount).toBe(NODE_BUDGET);
  });

  it("never drops a selected (kept) node, a response node, a cluster or a non-leaf", () => {
    const g = fill(NODE_BUDGET);
    const ranked = g.graph
      .mapNodes((id, a) => ({ id, d: Math.hypot(a.x, a.y) }))
      .sort((a, b) => b.d - a.d);
    const selected = ranked[0]?.id as string; // the farthest node is selected
    const hub = ranked[1]?.id as string; // the second farthest has two edges (not a leaf)
    g.upsertEdges([edge("h1", hub, "n1"), edge("h2", hub, "n2")]);
    g.mergeNeighbourhood("centre", [node("centre")], [], new Set([selected]));
    expect(g.graph.hasNode(selected)).toBe(true);
    expect(g.graph.hasNode(hub)).toBe(true);
    expect(g.graph.hasNode("centre")).toBe(true);
    expect(g.nodeCount).toBe(NODE_BUDGET);
    const third = ranked[2]?.id as string;
    expect(g.graph.hasNode(third)).toBe(false); // the next-farthest unprotected leaf made room
  });

  it("skips what cannot fit when nothing is droppable, centre node first", () => {
    const g = new MapGraph();
    g.upsertNodes(
      Array.from({ length: NODE_BUDGET }, (_, i) => node(`c${i}`, { kind: "cluster" })),
    );
    const result = g.mergeNeighbourhood("centre", [node("a"), node("centre"), node("b")], []);
    expect(g.nodeCount).toBe(NODE_BUDGET);
    expect(result).toMatchObject({ added: 0, dropped: 0, skipped: 3, centred: false });
  });
});
