/**
 * Wire types for the viewport API and the realtime gateway, mirrored by hand from
 * services/api/neurosphere_api/map/models.py and realtime/source.py. Unknown metrics are null,
 * never 0; people arrive as pseudonyms and are rendered exactly as served.
 */

import type { MapNodeFacets, MapTopologyChange } from "@neurosphere/contracts";

export type { MapNodeFacets, MapTopologyChange };

export type NodeKind =
  | "person"
  | "agent"
  | "sub_agent"
  | "model"
  | "source"
  | "service"
  | "tool"
  | "mcp_server"
  | "cluster";
export type Health = "ok" | "degraded" | "failing" | "unknown";
export type Provenance = "observed" | "declared" | "inferred";
export type CoverageState = "complete" | "partial" | "delayed" | "unknown";
export type TruncationReason =
  "node_budget" | "edge_budget" | "scan_limit" | "traversal_incomplete" | "timeout_ms";

export const NODE_KINDS: readonly NodeKind[] = [
  "person",
  "agent",
  "sub_agent",
  "model",
  "source",
  "service",
  "tool",
  "mcp_server",
  "cluster",
];

export const PROVENANCES: readonly Provenance[] = ["observed", "declared", "inferred"];
export const HEALTHS: readonly Health[] = ["ok", "degraded", "failing", "unknown"];

/** The server clamps node_budget to this; the client never asks for, or holds, more. */
export const NODE_BUDGET = 2000;

export interface NodeMetrics {
  readonly tokens: number | null;
  readonly context_size: number | null;
  readonly frequency: number | null;
  readonly latency_p95_ms: number | null;
  readonly health: Health;
}

export interface ViewportNode {
  readonly id: string;
  readonly kind: NodeKind;
  readonly label: string;
  readonly cluster_id: string | null;
  readonly member_count: number | null;
  readonly metrics: NodeMetrics;
  /** Filterable facets and error figures; absent from older servers and from realtime deltas. */
  readonly facets?: MapNodeFacets | null;
  /** True when health comes from the dependents fallback rule, not a measured point. */
  readonly health_inferred?: boolean;
}

export interface ViewportEdge {
  readonly id: string;
  readonly source: string;
  readonly target: string;
  readonly provenance: Provenance;
  readonly last_observed_at: string | null;
}

export interface Coverage {
  readonly state: CoverageState;
  readonly lag_seconds: number | null;
  readonly as_of: string | null;
}

export interface ViewportResponse {
  readonly domain_id: string;
  readonly nodes: readonly ViewportNode[];
  readonly edges: readonly ViewportEdge[];
  readonly truncated: boolean;
  readonly truncation_reason: TruncationReason | null;
  readonly next_cursor: string | null;
  readonly coverage: Coverage;
}

export interface ViewportFilters {
  readonly node_type: readonly string[];
  readonly tag: readonly string[];
  readonly environment: readonly string[];
  readonly cloud: readonly string[];
  readonly health: readonly string[];
}

/** The neighbourhood route returns the viewport shape: one node and its direct neighbours. */
export type NeighborhoodResponse = ViewportResponse;

export interface SearchMatch {
  readonly node: ViewportNode;
  readonly cluster_id: string;
}

export interface SearchCounts {
  readonly by_kind: Readonly<Record<string, number>>;
  readonly by_health: Readonly<Record<string, number>>;
  readonly by_environment: Readonly<Record<string, number>>;
  readonly by_cloud: Readonly<Record<string, number>>;
}

export interface SearchResponse {
  readonly domain_id: string;
  readonly matches: readonly SearchMatch[];
  readonly counts: SearchCounts;
  readonly truncated: boolean;
  readonly truncation_reason: TruncationReason | null;
  readonly coverage: Coverage;
  readonly filters_applied?: ViewportFilters | null;
}

export interface ImpactBudget {
  readonly max_accessors?: number | null;
  readonly timeout_ms?: number | null;
}

/** Body of POST /api/v1/map/domains/{domain_id}/impact. */
export interface ImpactRequest {
  readonly node_id: string;
  /** 1 to 5; the server default is 3, the map asks for 2. */
  readonly max_depth: number;
  readonly budget?: ImpactBudget | null;
}

export interface ImpactNode {
  readonly id: string;
  readonly kind: NodeKind;
  readonly label: string;
  readonly domain_id: string;
  readonly health: Health;
  readonly health_inferred?: boolean;
}

export interface ImpactLevel {
  readonly depth: number;
  readonly nodes: readonly ImpactNode[];
  readonly edge_ids: readonly string[];
}

export interface ImpactResponse {
  readonly domain_id: string;
  readonly node_id: string;
  readonly direction: "dependents";
  readonly levels: readonly ImpactLevel[];
  readonly truncated: boolean;
  readonly truncation_reason: TruncationReason | null;
  readonly coverage: Coverage;
}

/** Realtime notice that the topology changed; carries ids only, the client refetches. */
export type TopologyMessage = MapTopologyChange & {
  readonly type: "topology";
  readonly seq: number;
  readonly emitted_at: string;
};

export interface DeltaMessage {
  readonly type: "delta";
  readonly domain_id: string;
  readonly seq: number;
  readonly nodes: readonly ViewportNode[];
  readonly edges: readonly ViewportEdge[];
  readonly coverage: Coverage;
  readonly emitted_at: string;
}

/** What a legend can size nodes by. */
export type SizeMetric = "tokens" | "context_size" | "frequency" | "latency_p95_ms" | "error_rate";

/** Size metrics held in `NodeMetrics`; `error_rate` comes from the node facets instead. */
export type MetricKey = Exclude<SizeMetric, "error_rate">;

export const METRIC_KEYS: readonly MetricKey[] = [
  "tokens",
  "context_size",
  "frequency",
  "latency_p95_ms",
];

export const SIZE_METRICS: readonly SizeMetric[] = [
  "tokens",
  "context_size",
  "frequency",
  "latency_p95_ms",
  "error_rate",
];
