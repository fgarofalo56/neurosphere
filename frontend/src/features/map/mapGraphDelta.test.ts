import { describe, expect, it } from "vitest";
import { MapGraph, NULL_METRICS } from "./mapGraph";
import type { ViewportNode } from "./types";

function node(
  id: string,
  kind: ViewportNode["kind"],
  label: string,
  over: Partial<ViewportNode> = {},
): ViewportNode {
  return { id, kind, label, cluster_id: null, member_count: null, metrics: NULL_METRICS, ...over };
}

function build(): MapGraph {
  const g = new MapGraph();
  g.upsertNodes([
    node("a1", "agent", "Support agent", { cluster_id: "kind:agent" }),
    node("sa1", "sub_agent", "Helper", { cluster_id: "kind:agent" }),
    node("m1", "model", "gpt-4o deployment"),
    node("src1", "source", "Wiki"),
    node("kind:agent", "cluster", "Agents", { member_count: 40 }),
  ]);
  g.restyle();
  return g;
}

const METRICS = { tokens: 120, frequency: 7, latency_p95_ms: 250, health: "degraded" };

describe("MapGraph.applyDelta (PRP-49)", () => {
  it("merges only metrics into an existing node and keeps label, cluster and member count", () => {
    const g = build();
    g.applyDelta(
      [
        { id: "a1", kind: "agent", label: "alpha", cluster_id: "other", metrics: METRICS },
        { id: "sa1", kind: "agent", label: "x", metrics: METRICS },
        { id: "m1", kind: "model", label: "gpt-4o", member_count: 9, metrics: METRICS },
      ],
      [],
    );
    const a1 = g.graph.getNodeAttributes("a1");
    expect(a1.label).toBe("Support agent");
    expect(a1.clusterId).toBe("kind:agent");
    expect(a1.kind).toBe("agent");
    expect(a1.metrics).toMatchObject({ frequency: 7, tokens: 120, health: "degraded" });
    expect(g.graph.getNodeAttribute("sa1", "kind")).toBe("sub_agent"); // kind is not overwritten
    expect(g.graph.getNodeAttribute("m1", "label")).toBe("gpt-4o deployment");
    expect(g.graph.getNodeAttribute("m1", "memberCount")).toBeNull();
  });

  it("ignores agent, sub_agent, model and source nodes whose id is not in the graph", () => {
    const g = build();
    const before = g.nodeCount;
    g.applyDelta(
      ["agent", "sub_agent", "model", "source"].map((kind, i) => ({
        id: `unknown-${i}`,
        kind,
        label: "new",
        metrics: METRICS,
      })),
      [],
    );
    expect(g.nodeCount).toBe(before);
  });

  it("still upserts the domain cluster node", () => {
    const g = build();
    g.applyDelta(
      [{ id: "dom-1", kind: "cluster", label: "finance", metrics: { health: "failing" } }],
      [],
    );
    expect(g.graph.hasNode("dom-1")).toBe(true);
    expect(g.graph.getNodeAttribute("dom-1", "metrics").health).toBe("failing");
    g.applyDelta(
      [{ id: "dom-1", kind: "cluster", label: "finance", metrics: { health: "ok" } }],
      [],
    );
    expect(g.graph.getNodeAttribute("dom-1", "metrics").health).toBe("ok");
  });

  it("keeps unknown metric values null rather than 0", () => {
    const g = build();
    g.applyDelta([{ id: "a1", kind: "agent", label: "a", metrics: { health: "ok" } }], []);
    const metrics = g.graph.getNodeAttribute("a1", "metrics");
    expect(metrics.tokens).toBeNull();
    expect(metrics.latency_p95_ms).toBeNull();
    expect(metrics.health).toBe("ok");
  });
});
