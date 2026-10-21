/**
 * The graphology model behind the map. Pure data (no sigma, no DOM): builds nodes and edges from
 * viewport pages and realtime deltas, lays them out deterministically and derives the render
 * attributes (size, colour, shape, edge dash style) from the current legend settings.
 */
import Graph from "graphology";
import {
  edgeAppearance,
  kindSigmaShape,
  metricRange,
  metricValue,
  nodeAppearance,
  type MetricRange,
} from "./appearance";
import {
  HEALTHS,
  NODE_BUDGET,
  NODE_KINDS,
  PROVENANCES,
  type Coverage,
  type CoverageState,
  type NodeKind,
  type NodeMetrics,
  type SizeMetric,
  type ViewportEdge,
  type ViewportNode,
} from "./types";

export interface MapNodeAttributes {
  x: number;
  y: number;
  size: number;
  color: string;
  opacity: number;
  shape: string;
  label: string;
  kind: NodeKind;
  clusterId: string | null;
  memberCount: number | null;
  metrics: NodeMetrics;
  sizeUnknown: boolean;
  [key: string]: unknown;
}

export interface MapEdgeAttributes {
  size: number;
  color: string;
  dashSize: number;
  gapSize: number;
  dashOffset: number;
  provenance: ViewportEdge["provenance"];
  animated: boolean;
  lastObservedAt: string | null;
  [key: string]: unknown;
}

export interface MapSettings {
  readonly sizeBy: SizeMetric;
  /** True when observed edges may animate (reduced motion is off). */
  readonly animateEdges: boolean;
}

export const DEFAULT_SETTINGS: MapSettings = { sizeBy: "tokens", animateEdges: true };

const ISLAND_RADIUS = 520;
const POINT_SPACING = 10;
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

/** Deterministic island layout: one phyllotaxis disc per kind, so positions never jump. */
export function layoutPosition(kind: NodeKind, indexInKind: number): { x: number; y: number } {
  const slot = NODE_KINDS.indexOf(kind);
  const centreAngle = (slot / NODE_KINDS.length) * Math.PI * 2;
  const cx = Math.cos(centreAngle) * ISLAND_RADIUS;
  const cy = Math.sin(centreAngle) * ISLAND_RADIUS;
  return spiralPosition(cx, cy, indexInKind);
}

function spiralPosition(cx: number, cy: number, index: number): { x: number; y: number } {
  const r = POINT_SPACING * Math.sqrt(index + 1);
  const a = index * GOLDEN_ANGLE;
  return { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) };
}

/** Worst state wins; a gap is never smoothed over by a later complete page. */
const COVERAGE_SEVERITY: Readonly<Record<CoverageState, number>> = {
  complete: 0,
  partial: 1,
  delayed: 2,
  unknown: 3,
};

export function worstCoverage(sources: Iterable<Coverage>): Coverage | null {
  let worst: Coverage | null = null;
  let lag: number | null = null;
  for (const c of sources) {
    if (c.lag_seconds !== null) lag = lag === null ? c.lag_seconds : Math.max(lag, c.lag_seconds);
    if (worst === null || COVERAGE_SEVERITY[c.state] > COVERAGE_SEVERITY[worst.state]) worst = c;
  }
  return worst === null ? null : { state: worst.state, lag_seconds: lag, as_of: worst.as_of };
}

const NULL_METRICS: NodeMetrics = {
  tokens: null,
  context_size: null,
  frequency: null,
  latency_p95_ms: null,
  health: "unknown",
};

function numOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Validates an untrusted node (a realtime delta); returns null when it is not usable. */
export function parseNode(raw: unknown): ViewportNode | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Record<string, unknown>;
  if (typeof r["id"] !== "string" || r["id"] === "") return null;
  if (typeof r["kind"] !== "string" || !(NODE_KINDS as readonly string[]).includes(r["kind"])) {
    return null;
  }
  const m =
    typeof r["metrics"] === "object" && r["metrics"] !== null
      ? (r["metrics"] as Record<string, unknown>)
      : {};
  const health = (HEALTHS as readonly unknown[]).includes(m["health"])
    ? (m["health"] as NodeMetrics["health"])
    : "unknown";
  return {
    id: r["id"],
    kind: r["kind"] as NodeKind,
    label: typeof r["label"] === "string" ? r["label"] : r["id"],
    cluster_id: typeof r["cluster_id"] === "string" ? r["cluster_id"] : null,
    member_count: numOrNull(r["member_count"]),
    metrics: {
      tokens: numOrNull(m["tokens"]),
      context_size: numOrNull(m["context_size"]),
      frequency: numOrNull(m["frequency"]),
      latency_p95_ms: numOrNull(m["latency_p95_ms"]),
      health,
    },
  };
}

export function parseEdge(raw: unknown): ViewportEdge | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Record<string, unknown>;
  if (typeof r["id"] !== "string" || typeof r["source"] !== "string") return null;
  if (typeof r["target"] !== "string") return null;
  if (!(PROVENANCES as readonly unknown[]).includes(r["provenance"])) return null;
  return {
    id: r["id"],
    source: r["source"],
    target: r["target"],
    provenance: r["provenance"] as ViewportEdge["provenance"],
    last_observed_at: typeof r["last_observed_at"] === "string" ? r["last_observed_at"] : null,
  };
}

export class MapGraph {
  readonly graph = new Graph<MapNodeAttributes, MapEdgeAttributes>({
    type: "directed",
    multi: true,
    allowSelfLoops: true,
  });
  private readonly kindCounts = new Map<NodeKind, number>();
  private readonly clusterCounts = new Map<string, number>();
  /** Edges whose endpoints have not been loaded yet (a later page may supply them). */
  private readonly pendingEdges = new Map<string, ViewportEdge>();
  private settings: MapSettings = DEFAULT_SETTINGS;

  get nodeCount(): number {
    return this.graph.order;
  }

  get edgeCount(): number {
    return this.graph.size;
  }

  get remainingBudget(): number {
    return Math.max(0, NODE_BUDGET - this.graph.order);
  }

  getSettings(): MapSettings {
    return this.settings;
  }

  /**
   * Adds or updates nodes. New nodes beyond the display budget are dropped (the browser never
   * holds more than NODE_BUDGET nodes); returns the number of dropped nodes.
   */
  upsertNodes(nodes: readonly ViewportNode[]): number {
    let dropped = 0;
    for (const node of nodes) {
      const existing = this.graph.hasNode(node.id);
      if (!existing && this.graph.order >= NODE_BUDGET) {
        dropped += 1;
        continue;
      }
      const base = {
        label: node.label,
        kind: node.kind,
        clusterId: node.cluster_id,
        memberCount: node.member_count,
        metrics: node.metrics,
        shape: kindSigmaShape(node.kind),
      };
      if (existing) {
        this.graph.mergeNodeAttributes(node.id, base);
      } else {
        const { x, y } = this.placeNew(node);
        this.graph.addNode(node.id, {
          ...base,
          x,
          y,
          size: 4,
          color: "#8a8886",
          opacity: 1,
          sizeUnknown: true,
        });
      }
    }
    return dropped;
  }

  /** Members of a loaded cluster spiral around it; everything else joins its kind's island. */
  private placeNew(node: ViewportNode): { x: number; y: number } {
    const clusterId = node.cluster_id;
    if (clusterId !== null && clusterId !== node.id && this.graph.hasNode(clusterId)) {
      const centre = this.graph.getNodeAttributes(clusterId);
      const index = this.clusterCounts.get(clusterId) ?? 0;
      this.clusterCounts.set(clusterId, index + 1);
      return spiralPosition(centre.x, centre.y, index + 3);
    }
    const index = this.kindCounts.get(node.kind) ?? 0;
    this.kindCounts.set(node.kind, index + 1);
    return layoutPosition(node.kind, index);
  }

  upsertEdges(edges: readonly ViewportEdge[]): void {
    for (const edge of edges) this.pendingEdges.set(edge.id, edge);
    this.flushPendingEdges();
  }

  private flushPendingEdges(): void {
    for (const [id, edge] of this.pendingEdges) {
      if (!this.graph.hasNode(edge.source) || !this.graph.hasNode(edge.target)) continue;
      this.pendingEdges.delete(id);
      const look = edgeAppearance(edge.provenance, this.settings.animateEdges);
      const attrs: MapEdgeAttributes = {
        size: look.size,
        color: look.color,
        dashSize: look.dashSize,
        gapSize: look.gapSize,
        dashOffset: 1,
        provenance: edge.provenance,
        animated: look.animated,
        lastObservedAt: edge.last_observed_at,
      };
      if (this.graph.hasEdge(id)) {
        this.graph.replaceEdgeAttributes(id, attrs);
      } else {
        this.graph.addEdgeWithKey(id, edge.source, edge.target, attrs);
      }
    }
  }

  /** Re-derives size, colour and edge style from the legend settings. */
  restyle(settings: MapSettings = this.settings): void {
    this.settings = settings;
    const g = this.graph;
    const range: MetricRange | null = metricRange(
      g.mapNodes((_, a) => (a.kind === "cluster" ? null : metricValue(a.metrics, settings.sizeBy))),
    );
    const memberRange: MetricRange | null = metricRange(
      g.mapNodes((_, a) => (a.kind === "cluster" ? a.memberCount : null)),
    );
    g.forEachNode((id, a) => {
      const look = nodeAppearance(
        a.kind,
        a.metrics,
        a.memberCount,
        settings.sizeBy,
        range,
        memberRange,
      );
      g.mergeNodeAttributes(id, {
        size: look.size,
        color: look.color,
        opacity: look.opacity,
        sizeUnknown: look.sizeUnknown,
      });
    });
    g.forEachEdge((id, a) => {
      const look = edgeAppearance(a.provenance, settings.animateEdges);
      g.mergeEdgeAttributes(id, {
        color: look.color,
        size: look.size,
        dashSize: look.dashSize,
        gapSize: look.gapSize,
        animated: look.animated,
        dashOffset: 1,
      });
    });
  }

  /** Ids of the edges that animate (observed only, and only when motion is allowed). */
  animatedEdgeIds(): string[] {
    if (!this.settings.animateEdges) return [];
    return this.graph.filterEdges((_, a) => a.animated);
  }

  /** Min/max of the known values of a metric, for the size legend. */
  sizeRange(metric: SizeMetric): MetricRange | null {
    return metricRange(
      this.graph.mapNodes((_, a) => (a.kind === "cluster" ? null : metricValue(a.metrics, metric))),
    );
  }

  countUnknownSize(): number {
    let n = 0;
    this.graph.forEachNode((_, a) => {
      if (a.sizeUnknown) n += 1;
    });
    return n;
  }

  /** Applies one realtime delta: validated upserts only; unknown shapes are ignored. */
  applyDelta(rawNodes: readonly unknown[], rawEdges: readonly unknown[]): void {
    const nodes = rawNodes.map(parseNode).filter((n): n is ViewportNode => n !== null);
    const edges = rawEdges.map(parseEdge).filter((e): e is ViewportEdge => e !== null);
    this.upsertNodes(nodes);
    this.upsertEdges(edges);
    this.restyle();
  }
}

export { NULL_METRICS };
