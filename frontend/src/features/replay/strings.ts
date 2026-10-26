/** Every label for replay lives here so tests assert exact text. Status is never colour alone. */
import type { GapReason, Sampling, Span } from "./types";

export const STRINGS = {
  title: "Trace replay",
  readOnly: "Read-only view of stored, redacted traces. Nothing here runs or changes anything.",
  domainRequired: "Choose a domain to view its traces.",
  noTraces: "No traces found for this domain.",
  traceList: "Traces",
  openTrace: "Inspect trace",
  columns: {
    trace: "Trace",
    root: "Root span",
    spans: "Spans",
    errors: "Errors",
    started: "Started",
  },
  loadMore: "Show more traces",
  loading: "Loading...",
  treeLabel: "Trace spans",
  error: "Error",
  tool: "Tool",
  late: "Late",
  unknownDuration: "duration unknown",
  gapsHeading: "Gaps",
  noGaps: "No gaps detected",
  partial: "Partial trace",
  complete: "Complete trace",
  truncated: "Truncated: the archive scan stopped before the end of the window.",
  payloadHidden: "Payload not shown (off by default)",
  gapReason: {
    missing_parent: "Gap: missing parent",
    sampled_out: "Gap: parent sampled out",
    late_arrival: "Gap: parent not arrived yet",
    unknown: "Gap: unknown cause",
  } satisfies Record<GapReason, string>,
} as const;

export function durationText(ms: number | null): string {
  if (ms === null) return STRINGS.unknownDuration;
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${ms} ms`;
}

export function samplingText(rate: number | null): string {
  if (rate === null) return "Sampling: not reported";
  if (rate >= 1) return "Sampling: none (100%)";
  return `Sampled at ${Math.round(rate * 1000) / 10}%`;
}

export function traceSamplingText(s: Sampling): string {
  const base = samplingText(s.rate);
  return s.reason !== null ? `${base} (${s.reason})` : base;
}

export function spanLabel(span: Span): string {
  const parts = [span.name, span.kind, durationText(span.duration_ms)];
  if (span.status === "error") parts.push(STRINGS.error);
  if (span.late) parts.push(STRINGS.late);
  if (span.sampled) parts.push(samplingText(span.sampling_rate));
  return parts.join(", ");
}
