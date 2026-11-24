import { describe, expect, it } from "vitest";
import { concernsImpact, deriveImpact, highlightOf, type GraphPresence } from "./impactState";
import type { ImpactResponse } from "../types";

const COVERAGE = { state: "complete", lag_seconds: 0, as_of: "2026-10-20T10:00:00Z" } as const;

function node(id: string, health: "ok" | "failing" | "degraded" | "unknown" = "ok") {
  return { id, kind: "agent", label: id, domain_id: "d1", health } as const;
}

const RESPONSE: ImpactResponse = {
  domain_id: "d1",
  node_id: "svc",
  direction: "dependents",
  levels: [
    // Deliberately out of order: the state sorts by depth.
    { depth: 2, nodes: [node("c", "failing"), node("off")], edge_ids: ["e2", "e-off"] },
    { depth: 1, nodes: [node("a"), node("b", "degraded")], edge_ids: ["e1"] },
  ],
  truncated: false,
  truncation_reason: null,
  coverage: COVERAGE,
};

function graphOf(nodes: string[], edges: string[]): GraphPresence {
  return { hasNode: (id) => nodes.includes(id), hasEdge: (id) => edges.includes(id) };
}

describe("deriveImpact", () => {
  const graph = graphOf(["svc", "a", "b", "c"], ["e1", "e2"]);

  it("collects the affected node and edge sets from every level", () => {
    const state = deriveImpact(RESPONSE, graph);
    expect([...state.nodeIds].sort()).toEqual(["a", "b", "c", "off"]);
    expect([...state.edgeIds].sort()).toEqual(["e-off", "e1", "e2"]);
    expect(state.rootId).toBe("svc");
    expect(state.total).toBe(4);
  });

  it("lists nodes per depth in ascending order with their health", () => {
    const state = deriveImpact(RESPONSE, graph);
    expect(state.levels.map((l) => l.depth)).toEqual([1, 2]);
    expect(state.levels[0]?.rows.map((r) => [r.id, r.health])).toEqual([
      ["a", "ok"],
      ["b", "degraded"],
    ]);
    expect(state.levels[1]?.rows.map((r) => [r.id, r.health])).toEqual([
      ["c", "failing"],
      ["off", "ok"],
    ]);
  });

  it("lists a node once, at its shortest depth", () => {
    const state = deriveImpact(
      {
        ...RESPONSE,
        levels: [
          { depth: 1, nodes: [node("a")], edge_ids: [] },
          { depth: 2, nodes: [node("a"), node("c")], edge_ids: [] },
        ],
      },
      graph,
    );
    expect(state.levels[1]?.rows.map((r) => r.id)).toEqual(["c"]);
    expect(state.total).toBe(2);
  });

  it("finds the dependents the map does not hold", () => {
    const state = deriveImpact(RESPONSE, graph);
    expect(state.offscreen.map((r) => r.id)).toEqual(["off"]);
    expect(state.levels[1]?.rows.find((r) => r.id === "off")?.onScreen).toBe(false);
    expect(state.levels[0]?.rows.every((r) => r.onScreen)).toBe(true);
  });

  it("reports an empty result without failing", () => {
    const state = deriveImpact({ ...RESPONSE, levels: [] }, graph);
    expect(state.total).toBe(0);
    expect(state.offscreen).toEqual([]);
  });
});

describe("highlightOf", () => {
  const graph = graphOf(["svc", "a", "b", "c"], ["e1", "e2"]);

  it("highlights the root plus the dependents and edges that are on screen", () => {
    const highlight = highlightOf(deriveImpact(RESPONSE, graph), graph);
    expect([...(highlight?.nodeIds ?? [])].sort()).toEqual(["a", "b", "c", "svc"]);
    expect([...(highlight?.edgeIds ?? [])].sort()).toEqual(["e1", "e2"]);
  });

  it("is null when cleared, so the previous view returns", () => {
    expect(highlightOf(null, graph)).toBeNull();
  });
});

describe("concernsImpact", () => {
  it("is true for the root and for any dependent, false otherwise", () => {
    const state = deriveImpact(RESPONSE, graphOf([], []));
    expect(concernsImpact(state, "svc")).toBe(true);
    expect(concernsImpact(state, "c")).toBe(true);
    expect(concernsImpact(state, "other")).toBe(false);
    expect(concernsImpact(null, "svc")).toBe(false);
  });
});
