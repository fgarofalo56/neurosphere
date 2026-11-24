import { describe, expect, it } from "vitest";
import { MapGraph, NULL_METRICS, parseNode } from "./mapGraph";
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

describe("MapGraph.applyDelta merge and new kinds (PRP-77)", () => {
  const FULL = { tokens: 500, context_size: 8192, frequency: 3, latency_p95_ms: 120, health: "ok" };

  it("keeps the last known value when a delta metric is null or absent", () => {
    const g = build();
    g.applyDelta([{ id: "a1", kind: "agent", label: "a", metrics: FULL }], []);
    g.applyDelta(
      [{ id: "a1", kind: "agent", label: "a", metrics: { context_size: null, tokens: 900 } }],
      [],
    );
    const m = g.graph.getNodeAttribute("a1", "metrics");
    expect(m.context_size).toBe(8192);
    expect(m.tokens).toBe(900);
    expect(m.frequency).toBe(3);
    expect(m.latency_p95_ms).toBe(120);
  });

  it("updates a model node's metrics live from a delta carrying its viewport id", () => {
    const g = build();
    g.applyDelta([{ id: "m1", kind: "model", label: "ignored", metrics: FULL }], []);
    expect(g.graph.getNodeAttribute("m1", "metrics")).toMatchObject({ tokens: 500, health: "ok" });
    expect(g.graph.getNodeAttribute("m1", "label")).toBe("gpt-4o deployment");
    expect(g.graph.getNodeAttribute("m1", "sizeUnknown")).toBe(false);
  });

  it("parses the new kinds and the facets", () => {
    const facets = {
      environment: "production",
      cloud: "government",
      tags: ["pii", "tier-1"],
      health: "failing",
      error_rate: 0.25,
      error_count: 5,
      last_error_at: "2026-11-24T10:00:00Z",
      bogus: "dropped",
    };
    for (const kind of ["service", "tool", "mcp_server"]) {
      const parsed = parseNode({ id: `x-${kind}`, kind, label: kind, facets });
      expect(parsed?.kind).toBe(kind);
      expect(parsed?.facets).toEqual({
        environment: "production",
        cloud: "government",
        tags: ["pii", "tier-1"],
        health: "failing",
        error_rate: 0.25,
        error_count: 5,
        last_error_at: "2026-11-24T10:00:00Z",
      });
    }
    expect(parseNode({ id: "a", kind: "agent" })?.facets).toBeUndefined();
  });

  it("treats an unknown kind as a generic node with its label, never dropping it", () => {
    const parsed = parseNode({ id: "z1", kind: "quantum_widget", label: "Widget" });
    expect(parsed).toMatchObject({ id: "z1", kind: "quantum_widget", label: "Widget" });
    const g = new MapGraph();
    g.upsertNodes([parsed as ViewportNode]);
    g.restyle();
    expect(g.graph.getNodeAttribute("z1", "label")).toBe("Widget");
    expect(g.graph.getNodeAttribute("z1", "shape")).toBe("circle");
  });

  it("sizes by error rate from the facets, and marks a node without one unknown", () => {
    const g = new MapGraph();
    g.upsertNodes([
      node("s1", "service", "api", { facets: { error_rate: 0.5 } }),
      node("s2", "service", "db", { facets: { error_rate: 0.1 } }),
      node("s3", "tool", "search"),
    ]);
    g.restyle({ ...g.getSettings(), sizeBy: "error_rate" });
    expect(g.sizeRange("error_rate")).toEqual({ min: 0.1, max: 0.5 });
    expect(g.graph.getNodeAttribute("s1", "size")).toBeGreaterThan(
      g.graph.getNodeAttribute("s2", "size"),
    );
    expect(g.graph.getNodeAttribute("s3", "sizeUnknown")).toBe(true);
  });

  it("does not create service, tool, mcp_server or unknown nodes from a delta", () => {
    const g = build();
    const before = g.nodeCount;
    g.applyDelta(
      ["service", "tool", "mcp_server", "alien"].map((kind) => ({
        id: `new-${kind}`,
        kind,
        label: "new",
        metrics: FULL,
      })),
      [],
    );
    expect(g.nodeCount).toBe(before);
  });
});
