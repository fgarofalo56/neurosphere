/** Local types for the reconciliation wire contract (GET /api/v1/reconciliation/domains/{domain}). */

export type SourceName = "gateway" | "app" | "billing";
export type Granularity = "request" | "vendor" | "unknown";

export interface MetricValue {
  readonly value: number | null;
  readonly status: "known" | "unknown";
  readonly complete: boolean;
  readonly price_version: { readonly id: string; readonly effective_date: string } | null;
}

export interface Freshness {
  readonly watermark: string | null;
  readonly lag_seconds: number | null;
  readonly billing_source_freshness: string | null;
}

export interface Reference {
  readonly label: string;
  readonly amount: MetricValue;
  readonly currency: string | null;
}

/** One reference per currency bucket; currencies are never added. */
export interface ReferenceLine extends Reference {
  readonly entry_count: number;
  readonly unknown_entry_count: number;
}

/** One entry per (source, currency). */
export interface SourceLine {
  readonly source: SourceName;
  readonly granularity: Granularity;
  readonly amount: MetricValue;
  readonly coverage: MetricValue;
  readonly variance: MetricValue;
  readonly currency: string | null;
}

export interface ReconciliationResponse {
  readonly domain_id: string;
  readonly window: { readonly start: string; readonly end: string };
  readonly freshness: Freshness;
  readonly complete: boolean;
  readonly truncated: boolean;
  readonly reference: Reference;
  readonly references: readonly ReferenceLine[];
  readonly sources: readonly SourceLine[];
  /** A count of ledger entries whose amount is unknown (unit "entries"). */
  readonly unknown_remainder: MetricValue & { readonly unit: "entries" };
  readonly disclaimer: "not_all_spend_observable";
}

export interface ReconciliationParams {
  readonly domainId: string;
  readonly days: number;
}
