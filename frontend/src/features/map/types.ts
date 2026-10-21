/**
 * Wire types for the viewport API and the realtime gateway, mirrored by hand from
 * services/api/neurosphere_api/map/models.py and realtime/source.py. Unknown metrics are null,
 * never 0; people arrive as pseudonyms and are rendered exactly as served.
 */

export type NodeKind = "person" | "agent" | "sub_agent" | "model" | "source" | "cluster";
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
export type SizeMetric = "tokens" | "context_size" | "frequency" | "latency_p95_ms";

export const SIZE_METRICS: readonly SizeMetric[] = [
  "tokens",
  "context_size",
  "frequency",
  "latency_p95_ms",
];
