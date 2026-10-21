/** Replay wire types (PRP-18 wire contract, read-only). Mirrors services/api/.../replay/models.py. */

export type SpanKind = "agent" | "model" | "tool" | "retrieval" | "other";
export type SpanStatus = "ok" | "error" | "unknown";
export type GapReason = "missing_parent" | "sampled_out" | "late_arrival" | "unknown";
export type PayloadState =
  "absent" | "redacted" | "pending" | "redaction_failed" | "not_required" | "unknown";
export type ToolOutcome = "success" | "error" | "cancelled" | "timeout" | "unknown";

export interface ToolInfo {
  name: string | null;
  outcome: ToolOutcome;
}

export interface Span {
  span_id: string;
  parent_span_id: string | null;
  name: string;
  kind: SpanKind;
  started_at: string;
  ended_at: string | null;
  duration_ms: number | null;
  status: SpanStatus;
  error: string | null;
  tool: ToolInfo | null;
  agent: string | null;
  late: boolean;
  late_reason: string | null;
  sampled: boolean;
  sampling_rate: number | null;
  payload_state: PayloadState;
  payload: Record<string, unknown> | null;
}

export interface Gap {
  parent_span_id: string | null;
  reason: GapReason;
  span_id: string | null;
  count: number;
  detail: string;
}

export interface Sampling {
  rate: number | null;
  reason: string | null;
}

export interface Completeness {
  state: "complete" | "partial" | "unknown";
  span_count: number;
  gap_count: number;
  late_count: number;
  withheld_span_count: number;
  truncated: boolean;
}

export interface TraceDetail {
  trace_id: string;
  spans: Span[];
  gaps: Gap[];
  sampling: Sampling;
  completeness: Completeness;
}

export interface TraceSummary {
  trace_id: string;
  started_at: string;
  span_count: number;
  error_count: number;
  sampling_rate: number | null;
  root_name: string | null;
}

export interface TracePage {
  items: TraceSummary[];
  next_cursor: string | null;
}

export interface TraceNode {
  readonly span: Span;
  readonly children: readonly TraceNode[];
  /** Gaps attached to this span (it is orphaned). */
  readonly gaps: readonly Gap[];
}
