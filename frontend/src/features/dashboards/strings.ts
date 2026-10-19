/** Every status string for dashboards lives here so tests assert exact values. No vendor names. */
import type { AnalyticsState, PriceVersion } from "./types";

export const STRINGS = {
  unknown: "unknown",
  estimated: "estimated",
  invoiced: "invoiced",
  incompleteTotal: "incomplete total (partial sum of known parts)",
  incompleteData: "incomplete data",
  truncated: "truncated series",
  priceVersionUnknown: "price version: unknown",
  watermarkLabel: "Data watermark",
  lagLabel: "Lag",
  billingFreshnessLabel: "Billing source freshness",
  analyticsState: {
    available: "analytics: available",
    delayed: "analytics: delayed",
    disabled: "analytics: disabled",
  } satisfies Record<AnalyticsState, string>,
  noReason: "no reason given",
} as const;

export function priceVersionText(pv: PriceVersion): string {
  return `price version ${pv.id} (effective ${pv.effective_date})`;
}

export function lagText(seconds: number): string {
  return `${seconds} s`;
}
