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
import { DEFAULT_MAP_THEME, type MapTheme } from "./mapTheme";
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
  /** Halo behind the node (tinted health background) and its glow colour. */
  haloColor: string;
  glowColor: string;
  /** "visible" while the graph is small enough for halos to be affordable. */
  halo: "visible" | "hidden";
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
  /** True when observed edges may animate (motion allowed, live, coverage complete/partial). */
  readonly animateEdges: boolean;
  /** Colours for nodes and edges, from the active UI style. */
  readonly theme: MapTheme;
}

export const DEFAULT_SETTINGS: MapSettings = {
  sizeBy: "tokens",
  animateEdges: true,
  theme: DEFAULT_MAP_THEME,
};

/** World units between neighbouring nodes. sigma fits the graph to the viewport, so only ratios matter. */
export const POINT_SPACING = 70;
/** The disc is stretched horizontally: labels are wide and the map frame is landscape. */
export const LAYOUT_ASPECT = 1.6;
/** Cluster members sit closer to their cluster than top-level nodes sit to each other. */
export const MEMBER_SPACING = 0.6 * POINT_SPACING;
/** Members start this many slots out so the first one never lands on the cluster itself. */
const MEMBER_INNER_SLOTS = 3;
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
/** Halos (backdrop + glow) are drawn only up to this many nodes: they cost fill rate. */
export const HALO_MAX_NODES = 150;

/**
 * Deterministic layout: a phyllotaxis (sunflower) disc, stretched to the landscape frame. The
 * position depends only on the arrival index, so the same input gives the same positions and
 * existing nodes never move when more arrive. Neighbours are at least ~POINT_SPACING apart at
 * any size, so a handful of nodes is as legible as a few hundred.
 */
export function layoutPosition(index: number): { x: number; y: number } {
  return spiralPosition(0, 0, index, POINT_SPACING);
}

function spiralPosition(
  cx: number,
  cy: number,
  index: number,
  spacing: number,
): { x: number; y: number } {
  const r = spacing * Math.sqrt(index);
  const a = index * GOLDEN_ANGLE;
  return { x: cx + r * Math.cos(a) * LAYOUT_ASPECT, y: cy + r * Math.sin(a) };
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
  /** Top-level nodes placed so far: the next arrival takes this slot on the disc. */
  private placed = 0;
  private readonly clusterCounts = new Map<string, number>();
  /** Edges whose endpoints have not been loaded yet (a later page may supply them). */
  private readonly pendingEdges = new Map<string, ViewportEdge>();
  private settings: MapSettings = DEFAULT_SETTINGS;
  /** Observed-edge ids, rebuilt only when edges or settings change (never per frame). */
  private animatedCache: string[] | null = null;

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
          color: this.settings.theme.health.unknown.icon,
          haloColor: this.settings.theme.health.unknown.bg,
          glowColor: "transparent",
          halo: "hidden",
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
      return spiralPosition(centre.x, centre.y, index + MEMBER_INNER_SLOTS, MEMBER_SPACING);
    }
    const index = this.placed;
    this.placed += 1;
    return layoutPosition(index);
  }

  upsertEdges(edges: readonly ViewportEdge[]): void {
    for (const edge of edges) this.pendingEdges.set(edge.id, edge);
    this.flushPendingEdges();
  }

  private flushPendingEdges(): void {
    this.animatedCache = null;
    for (const [id, edge] of this.pendingEdges) {
      if (!this.graph.hasNode(edge.source) || !this.graph.hasNode(edge.target)) continue;
      this.pendingEdges.delete(id);
      const look = edgeAppearance(edge.provenance, this.settings.animateEdges, this.settings.theme);
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
    this.animatedCache = null;
    const g = this.graph;
    const range: MetricRange | null = metricRange(
      g.mapNodes((_, a) => (a.kind === "cluster" ? null : metricValue(a.metrics, settings.sizeBy))),
    );
    const memberRange: MetricRange | null = metricRange(
      g.mapNodes((_, a) => (a.kind === "cluster" ? a.memberCount : null)),
    );
    const halo = g.order <= HALO_MAX_NODES ? "visible" : "hidden";
    g.forEachNode((id, a) => {
      const look = nodeAppearance(
        a.kind,
        a.metrics,
        a.memberCount,
        settings.sizeBy,
        range,
        memberRange,
        settings.theme,
      );
      g.mergeNodeAttributes(id, {
        size: look.size,
        color: look.color,
        haloColor: look.haloColor,
        glowColor: look.glowColor,
        halo,
        opacity: look.opacity,
        sizeUnknown: look.sizeUnknown,
      });
    });
    g.forEachEdge((id, a) => {
      const look = edgeAppearance(a.provenance, settings.animateEdges, settings.theme);
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
    this.animatedCache ??= this.graph.filterEdges((_, a) => a.animated);
    return this.animatedCache;
  }

  /** Drops every node and edge (access revoked: stale data must not stay drawn). */
  clear(): void {
    this.graph.clear();
    this.placed = 0;
    this.clusterCounts.clear();
    this.pendingEdges.clear();
    this.animatedCache = null;
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
