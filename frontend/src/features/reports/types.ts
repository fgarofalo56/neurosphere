import type { ChartPlan, StructuredQuery } from "@neurosphere/contracts";

export type { ChartPlan, StructuredQuery };

/** Hand-mirrored from services/api/neurosphere_api/reports/models.py (wire contract). */
export type PublicationState = "none" | "pending" | "approved" | "rejected";
export type ReportMetric = "cost" | "latency" | "errors";
export type Freshness = "fresh" | "stale" | "unknown";

export interface Publication {
  readonly state: PublicationState;
  readonly requested_by: string | null;
  readonly requested_at: string | null;
  readonly decided_by: string | null;
  readonly decided_at: string | null;
  readonly reason: string | null;
}

/** A stored report: plan template + bounded query. Never result data. */
export interface ReportView {
  readonly id: string;
  readonly domain_id: string;
  readonly owner: string;
  readonly title: string;
  readonly chart_plan: ChartPlan;
  readonly query_spec: StructuredQuery;
  readonly metric: ReportMetric;
  /** Empty for anyone but the owner. */
  readonly shares: readonly string[];
  readonly publication: Publication;
  readonly created_at: string;
  readonly updated_at: string;
  readonly etag: string;
  /** Server-computed UI hints; the API enforces regardless. */
  readonly is_owner: boolean;
  readonly can_decide_publication: boolean;
}

export interface ReportListResponse {
  readonly items: readonly ReportView[];
  readonly next_cursor: string | null;
}

export interface RunCitation {
  readonly record_id: string;
  readonly kind: string;
  readonly source: string;
  readonly as_of: string | null;
  readonly freshness: Freshness;
}

/** `no_data`: the viewer's own scope yields no rows (not an error, not a denial). */
export interface RunView {
  readonly report_id: string;
  readonly status: "ok" | "no_data";
  readonly chart_plan: ChartPlan | null;
  readonly citations: readonly RunCitation[];
  readonly truncated: boolean;
  readonly ran_at: string;
  readonly etag: string;
}

export interface ReportBody {
  readonly title: string;
  readonly chart_plan: ChartPlan;
  readonly query_spec: StructuredQuery;
  readonly metric: ReportMetric;
}

export interface ListParams {
  readonly domainId: string;
  readonly publicationState: PublicationState | "";
  readonly cursor: string;
  readonly limit: number;
}

export interface ReportParams {
  readonly domainId: string;
  readonly reportId: string;
}

export interface SaveVars {
  readonly domainId: string;
  readonly body: ReportBody;
}

export interface UpdateVars extends ReportParams {
  readonly body: ReportBody;
  readonly etag: string;
}

export interface DeleteVars extends ReportParams {
  readonly etag: string;
}

export interface ShareVars extends ReportParams {
  readonly principalId: string;
}

export interface DecideVars extends ReportParams {
  /** ETag of the ReportView the reviewer is looking at; the server refuses a stale one. */
  readonly etag: string;
  readonly decision: "approve" | "reject";
  readonly reason?: string | undefined;
}
