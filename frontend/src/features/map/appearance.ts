/**
 * Pure appearance rules (no sigma, no DOM): node shape per kind, size and colour legends, edge
 * styles per provenance. Unknown metrics get a distinct "unknown" style and are never plotted as 0.
 */
import { nodeTypeShape, type NodeShape, type NodeType } from "../../design-system";
import type { Health, NodeKind, NodeMetrics, Provenance, SizeMetric } from "./types";

/** Kind -> PRP-04 node-type icon type. Clusters are a map-only aggregate with no icon. */
export function kindToNodeType(kind: Exclude<NodeKind, "cluster">): NodeType {
  return kind === "sub_agent" ? "sub-agent" : kind;
}

/**
 * Container shape per kind, taken from the PRP-04 icon set so the canvas and the icons agree.
 * Clusters get their own shape ("triangle") so they never look like a member.
 */
export function kindShape(kind: NodeKind): NodeShape | "triangle" {
  return kind === "cluster" ? "triangle" : nodeTypeShape(kindToNodeType(kind));
}

/** sigma shape slug registered by the renderer for each container shape. */
export type SigmaShapeSlug = "circle" | "hexagon" | "diamond" | "square" | "rectangle" | "triangle";

export function sigmaShapeSlug(shape: NodeShape | "triangle"): SigmaShapeSlug {
  return shape === "pill" ? "rectangle" : shape;
}

export function kindSigmaShape(kind: NodeKind): SigmaShapeSlug {
  return sigmaShapeSlug(kindShape(kind));
}

// ---- colour by health. Fixed hues chosen for contrast on light and dark backgrounds; the
// health word is always present in the legend, the side panel and the table view.
export const HEALTH_COLOUR: Readonly<Record<Health, string>> = {
  ok: "#2e9e5b",
  degraded: "#d68a00",
  failing: "#d13438",
  unknown: "#8a8886",
};

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

export function metricValue(metrics: NodeMetrics, metric: SizeMetric): number | null {
  const value = metrics[metric];
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
): NodeAppearance {
  const color = HEALTH_COLOUR[metrics.health];
  if (kind === "cluster") {
    if (memberCount === null || memberRange === null) {
      return { size: CLUSTER_MIN_SIZE, color, opacity: UNKNOWN_OPACITY, sizeUnknown: true };
    }
    return {
      size: scale(memberCount, memberRange, CLUSTER_MIN_SIZE, CLUSTER_MAX_SIZE),
      color,
      opacity: 1,
      sizeUnknown: false,
    };
  }
  const value = metricValue(metrics, sizeBy);
  if (value === null || range === null) {
    return { size: UNKNOWN_SIZE, color, opacity: UNKNOWN_OPACITY, sizeUnknown: true };
  }
  return { size: scale(value, range, MIN_SIZE, MAX_SIZE), color, opacity: 1, sizeUnknown: false };
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

export const EDGE_COLOUR: Readonly<Record<Provenance, string>> = {
  observed: "#0f6cbd",
  declared: "#605e5c",
  inferred: "#a19f9d",
};

/**
 * Observed edges are solid; while animation is allowed they render as a flowing dash pattern
 * (offset advanced by the animator). Declared edges are dashed and inferred edges dotted, both
 * static in every motion mode.
 */
export function edgeAppearance(provenance: Provenance, animate: boolean): EdgeAppearance {
  switch (provenance) {
    case "observed":
      return animate
        ? { color: EDGE_COLOUR.observed, size: 1.5, dashSize: 8, gapSize: 4, animated: true }
        : {
            color: EDGE_COLOUR.observed,
            size: 1.5,
            dashSize: SOLID_DASH,
            gapSize: SOLID_GAP,
            animated: false,
          };
    case "declared":
      return { color: EDGE_COLOUR.declared, size: 1.2, dashSize: 12, gapSize: 6, animated: false };
    case "inferred":
      return { color: EDGE_COLOUR.inferred, size: 1, dashSize: 2, gapSize: 5, animated: false };
  }
}
