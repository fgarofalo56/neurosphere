/** Local types for the dashboards wire contract (GET /api/v1/dashboards/{metric}). */

export type DashboardMetric = "cost" | "latency" | "errors" | "coverage";
export type Grain = "day" | "hour";
export type AnalyticsState = "available" | "delayed" | "disabled";
export type SeriesKind = "estimated" | "invoiced";
export type SeriesUnit = "currency" | "ms" | "ratio" | "count";

export interface PriceVersion {
  readonly id: string;
  readonly effective_date: string;
}

export interface MetricValue {
  readonly value: number | null;
  readonly status: "known" | "unknown";
  readonly complete: boolean;
  readonly price_version: PriceVersion | null;
}

export interface SeriesPoint {
  readonly t: string;
  readonly value: MetricValue;
}

export interface Series {
  readonly key: string;
  readonly label: string;
  readonly kind: SeriesKind | null;
  readonly unit: SeriesUnit;
  readonly currency: string | null;
  readonly total: MetricValue;
  readonly points: readonly SeriesPoint[];
}

export interface Freshness {
  readonly watermark: string | null;
  readonly lag_seconds: number | null;
  readonly billing_source_freshness: string | null;
}

export interface DashboardResponse {
  readonly metric: DashboardMetric;
  readonly domain_id: string;
  readonly grain: Grain;
  readonly window: { readonly start: string; readonly end: string };
  readonly freshness: Freshness;
  readonly analytics: { readonly state: AnalyticsState; readonly reason: string | null };
  readonly complete: boolean;
  readonly truncated: boolean;
  readonly series: readonly Series[];
  readonly price_versions: readonly PriceVersion[];
}

export interface DashboardParams {
  readonly metric: DashboardMetric;
  readonly domainId: string;
  readonly days: number;
  readonly grain: Grain;
}
