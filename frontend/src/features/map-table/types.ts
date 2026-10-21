/** Mirrors services/api/neurosphere_api/map/models.py (the viewport wire contract). */
export type NodeKind = "person" | "agent" | "sub_agent" | "model" | "source" | "cluster";
export type Health = "ok" | "degraded" | "failing" | "unknown";
export type Provenance = "observed" | "declared" | "inferred";
export type CoverageState = "complete" | "partial" | "delayed" | "unknown";
export type TruncationReason =
  "node_budget" | "edge_budget" | "scan_limit" | "traversal_incomplete" | "timeout_ms";

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
