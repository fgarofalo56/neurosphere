import type { ContextEcho } from "./types";

/**
 * The bounded query stored with a report saved from a chat chart.
 *
 * LIMITATION: the `chart` event carries the validated plan but not the structured query that
 * produced its rows, so the UI cannot name the exact query the model's tools ran. Until the event
 * carries one, a report saved from chat re-runs a bounded daily cost aggregate under the viewer's
 * own scope (the server re-validates and re-authorizes on every run, so this can never widen
 * access). The time range follows what the server echoed for the question.
 */
export function defaultQuerySpec(echo: ContextEcho | null): Record<string, unknown> {
  const spec: Record<string, unknown> = {
    schema_version: "1.0.0",
    operation: "aggregate",
    entity: "cost_record",
    time_bucket: "day",
    budget: { timeout_ms: 2000, limit: 20, max_depth: 0 },
  };
  if (echo?.time_range != null) {
    spec["time_range"] = { start: echo.time_range.from, end: echo.time_range.to };
  }
  return spec;
}

/** The domain to preselect in the save dialog: only when the server applied exactly one. */
export function singleDomain(echo: ContextEcho | null): string {
  return echo?.applied_domains.length === 1 ? (echo.applied_domains[0] ?? "") : "";
}
