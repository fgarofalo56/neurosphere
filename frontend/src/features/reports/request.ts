import type { ChartPlan, ReportBody, ReportMetric, StructuredQuery } from "./types";

export const MAX_TITLE_LENGTH = 200;

export interface SaveReportInput {
  readonly title: string;
  /** The server-validated plan from the chat `chart` event (it may carry sample rows). */
  readonly chartPlan: ChartPlan;
  /** The bounded structured query that produced the plan's data. Never free-form text. */
  readonly querySpec: StructuredQuery;
  readonly metric?: ReportMetric | undefined;
}

/**
 * Builds the body of `POST /api/v1/reports/domains/{domain}/reports`. The domain is a path
 * segment, never a body field, and the body carries no identity or scope. The server validates
 * the plan again, stores the plan WITHOUT its rows and re-evaluates it per viewer on every run.
 * Returns `null` when the title is empty or too long.
 */
export function buildSaveReportRequest(input: SaveReportInput): ReportBody | null {
  const title = input.title.trim();
  if (title === "" || title.length > MAX_TITLE_LENGTH) return null;
  return {
    title,
    chart_plan: input.chartPlan,
    query_spec: input.querySpec,
    metric: input.metric ?? "cost",
  };
}
