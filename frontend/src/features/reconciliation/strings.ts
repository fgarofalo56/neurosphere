/** Every user-visible string of the reconciliation view. No vendor names. */
import type { Granularity, SourceName } from "./types";

export const STRINGS = {
  title: "Reconciliation",
  unknown: "unknown",
  notApplicable: "not applicable",
  undeterminedCurrency: "currency undetermined",
  disclaimer:
    "Not all spend is observable. These figures cover only spend reported by the gateway, application and billing sources; request-less vendor totals are shown separately and are not counted in the reference.",
  referenceLabel: "Reference: ledger (one record per request)",
  unknownRemainderLabel: "Entries with unknown amount",
  unknownRemainderNote:
    "Their money value is unknown, so it is not part of the reference or any variance.",
  incompleteData: "incomplete data",
  incompleteMarker: "incomplete",
  truncated: "truncated series",
  watermarkLabel: "Data watermark",
  lagLabel: "Lag",
  billingFreshnessLabel: "Billing source freshness",
  noData: "No reconciliation data in this window.",
  domainRequired: "Choose a domain to view reconciliation.",
  domainLabel: "Domain",
  daysLabel: "Days",
  apply: "Apply",
  filtersLabel: "Reconciliation filters",
  loading: "Loading reconciliation...",
  errorTitle: "Could not load reconciliation",
  errorBody: "The request failed. This is not an empty result. Try again later.",
  columns: {
    source: "Source",
    granularity: "Granularity",
    amount: "Amount",
    coverage: "Coverage",
    variance: "Variance vs reference",
  },
  sources: {
    gateway: "Gateway",
    app: "Application",
    billing: "Billing",
  } satisfies Record<SourceName, string>,
  granularity: {
    request: "per request",
    vendor: "vendor total (not per request)",
    unknown: "granularity unknown",
  } satisfies Record<Granularity, string>,
} as const;

export function lagText(seconds: number): string {
  return `${seconds} s`;
}
