/**
 * Pure appearance rules (no sigma, no DOM): node shape per kind, size and colour legends, edge
 * styles per provenance. Unknown metrics get a distinct "unknown" style and are never plotted as 0.
 * Colours come from the MapTheme (the active style's health tokens and Fluent tokens), never from
 * literals in this file.
 */
import { nodeTypeShape, type NodeShape, type NodeType } from "../../design-system";
import type { MapTheme } from "./mapTheme";
import type { MapNodeFacets, NodeKind, NodeMetrics, Provenance, SizeMetric } from "./types";

/** Kinds with a PRP-04 icon. Service, tool and MCP server nodes have a map shape only. */
export type CoreNodeKind = "person" | "agent" | "sub_agent" | "model" | "source";

const CORE_KINDS: ReadonlySet<string> = new Set([
  "person",
  "agent",
  "sub_agent",
  "model",
  "source",
]);

export function isCoreKind(kind: NodeKind): kind is CoreNodeKind {
  return CORE_KINDS.has(kind);
}

/** Kind -> PRP-04 node-type icon type. Clusters are a map-only aggregate with no icon. */
export function kindToNodeType(kind: CoreNodeKind): NodeType {
  return kind === "sub_agent" ? "sub-agent" : kind;
}

/** Map-only shapes for the PRP-70 kinds; each differs from every core shape and the cluster. */
export type ExtraShape = "pentagon" | "octagon" | "cross";

const EXTRA_SHAPE: Readonly<Record<"service" | "tool" | "mcp_server", ExtraShape>> = {
  service: "pentagon",
  tool: "cross",
  mcp_server: "octagon",
};

/**
 * Container shape per kind, taken from the PRP-04 icon set so the canvas and the icons agree.
 * Clusters get their own shape ("triangle") so they never look like a member.
 */
export function kindShape(kind: NodeKind): NodeShape | "triangle" | ExtraShape {
  if (kind === "cluster") return "triangle";
  if (isCoreKind(kind)) return nodeTypeShape(kindToNodeType(kind));
  // A kind from a newer server is a generic node: a plain circle with its label.
  return (EXTRA_SHAPE as Readonly<Record<string, ExtraShape | undefined>>)[kind] ?? "circle";
}

/** sigma shape slug registered by the renderer for each container shape. */
export type SigmaShapeSlug = "circle" | "hexagon" | "diamond" | "square" | "rectangle" | "triangle";

/**
 * The canvas registers six SDF shapes (renderer.ts). Until it registers the extra ones, a
 * service, tool or MCP server draws with the nearest registered slug; its own shape is the one
 * the legend shows, and its kind is always stated in text (panel, table, legend).
 */
const EXTRA_SIGMA_FALLBACK: Readonly<Record<ExtraShape, SigmaShapeSlug>> = {
  pentagon: "hexagon",
  octagon: "circle",
  cross: "diamond",
};

export function sigmaShapeSlug(shape: NodeShape | "triangle" | ExtraShape): SigmaShapeSlug {
  if (shape === "pill") return "rectangle";
  if (shape === "pentagon" || shape === "octagon" || shape === "cross") {
    return EXTRA_SIGMA_FALLBACK[shape];
  }
  return shape;
}

export function kindSigmaShape(kind: NodeKind): SigmaShapeSlug {
  return sigmaShapeSlug(kindShape(kind));
}

// Colour by health comes from the active style's health tokens (MapTheme.health): the fill is
// the icon colour, the halo the tinted background, the glow (ops console) the icon colour. The
// health word is always present in the legend, the side panel and the table view.

export const UNKNOWN_SIZE = 8;
export const UNKNOWN_OPACITY = 0.55;
export const MIN_SIZE = 9;
export const MAX_SIZE = 20;
export const CLUSTER_MIN_SIZE = 14;
export const CLUSTER_MAX_SIZE = 26;

export interface MetricRange {
  readonly min: number;
  readonly max: number;
}

export function metricValue(
  metrics: NodeMetrics,
  metric: SizeMetric,
  facets?: MapNodeFacets | null,
): number | null {
  const value = metric === "error_rate" ? facets?.error_rate : metrics[metric];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Range over the KNOWN values only; null when no node has the metric. */
export function metricRange(values: Iterable<number | null>): MetricRange | null {
  let min = Infinity;
  let max = -Infinity;
  for (const v of values) {
    if (v === null) continue;
    if (v < min) min = v;
    if (v > max) max = v;
  }
  return min === Infinity ? null : { min, max };
}

function scale(value: number, range: MetricRange, lo: number, hi: number): number {
  if (range.max === range.min) return (lo + hi) / 2;
  return lo + ((value - range.min) / (range.max - range.min)) * (hi - lo);
}

export interface NodeAppearance {
  readonly size: number;
  readonly color: string;
  /** Tinted halo drawn behind the node. */
  readonly haloColor: string;
  /** Glow of the halo; "transparent" when the style has no glow. */
  readonly glowColor: string;
  readonly opacity: number;
  /** True when the size metric is unknown for this node (rendered in the unknown style). */
  readonly sizeUnknown: boolean;
}

export function nodeAppearance(
  kind: NodeKind,
  metrics: NodeMetrics,
  memberCount: number | null,
  sizeBy: SizeMetric,
  range: MetricRange | null,
  memberRange: MetricRange | null,
  theme: MapTheme,
  facets?: MapNodeFacets | null,
): NodeAppearance {
  const health = theme.health[metrics.health];
  const base = {
    color: health.icon,
    haloColor: health.bg,
    glowColor: theme.glow ? health.icon : "transparent",
  };
  if (kind === "cluster") {
    if (memberCount === null || memberRange === null) {
      return { ...base, size: CLUSTER_MIN_SIZE, opacity: UNKNOWN_OPACITY, sizeUnknown: true };
    }
    return {
      ...base,
      size: scale(memberCount, memberRange, CLUSTER_MIN_SIZE, CLUSTER_MAX_SIZE),
      opacity: 1,
      sizeUnknown: false,
    };
  }
  const value = metricValue(metrics, sizeBy, facets);
  if (value === null || range === null) {
    return { ...base, size: UNKNOWN_SIZE, opacity: UNKNOWN_OPACITY, sizeUnknown: true };
  }
  return {
    ...base,
    size: scale(value, range, MIN_SIZE, MAX_SIZE),
    opacity: 1,
    sizeUnknown: false,
  };
}

// ---- edges. sigma's dashed layer treats a gap of 0 as "no pattern" and a size attribute of 0
// as "use the default", so a solid line is a very long dash with a ~0.2px gap.
export const SOLID_DASH = 100_000;
export const SOLID_GAP = 0.2;

export interface EdgeAppearance {
  readonly color: string;
  readonly size: number;
  readonly dashSize: number;
  readonly gapSize: number;
  /** Only observed edges ever animate. */
  readonly animated: boolean;
}

/**
 * Observed edges are solid; while animation is allowed they render as a flowing dash pattern
 * (offset advanced by the animator). Declared edges are dashed and inferred edges dotted, both
 * static in every motion mode.
 */
export function edgeAppearance(
  provenance: Provenance,
  animate: boolean,
  theme: MapTheme,
): EdgeAppearance {
  const color = theme.edge[provenance];
  switch (provenance) {
    case "observed":
      return animate
        ? { color, size: 1.5, dashSize: 8, gapSize: 4, animated: true }
        : { color, size: 1.5, dashSize: SOLID_DASH, gapSize: SOLID_GAP, animated: false };
    case "declared":
      return { color, size: 1.2, dashSize: 12, gapSize: 6, animated: false };
    case "inferred":
      return { color, size: 1, dashSize: 2, gapSize: 5, animated: false };
  }
}
