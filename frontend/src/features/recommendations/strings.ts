/** Every user-visible string for recommendations lives here so tests assert exact values. */
import type { RecommendationKind } from "./types";

export const STRINGS = {
  unknown: "unknown",
  advisory: "Advisory",
  advisoryReason: "action gates not passed",
  estimate: "Estimate",
  insufficientHistory: "Insufficient history",
  duplicateNote: "Consolidation review only; never merged automatically",
  routeToReview: "Route to review",
  routing: "Routing...",
  pendingReview: "Pending review",
  reviewRequestId: "Review request id",
  routeFailed: "Could not route to review",
  forbidden: "You do not have access to this domain",
  unavailable: "Recommendations are unavailable",
  unavailableDetail:
    "The service could not be reached. This is not an empty result. Try again later.",
  loading: "Loading...",
  domainRequired: "Choose a domain to view recommendations.",
  empty: "No recommendations match.",
  listTitle: "Recommendations",
  detailTitle: "Recommendation",
  back: "Back to recommendations",
  nextPage: "Next page",
  firstPage: "First page",
  kindLabel: "Kind",
  allKinds: "All kinds",
  searchLabel: "Search",
  domainLabel: "Domain",
  // Filter submit only; never a recommendation action (advisory until PRP-17 gates pass).
  apply: "Apply filters",
  evidenceNotSufficient: "Insufficient history",
  sections: {
    evidenceWindow: "Evidence window",
    coverage: "Coverage",
    uncertainty: "Uncertainty",
    prerequisites: "Prerequisites",
    estimate: "Estimate",
    owner: "Owner",
    generator: "Generator",
    evidenceIds: "Evidence ids",
    subjects: "Subjects",
    score: "Score",
  },
} as const;

export const KIND_LABELS: Record<RecommendationKind, string> = {
  cost_spike: "Cost spike",
  latency_degradation: "Latency degradation",
  error_rate_degradation: "Error rate degradation",
  unused_agent: "Unused agent",
  candidate_duplicate: "Candidate duplicate",
  model_right_sizing: "Model right-sizing",
};

/** Null, undefined and blank all render the literal "unknown", never 0 or an empty cell. */
export function orUnknown(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return STRINGS.unknown;
  const text = String(value);
  return text.trim() === "" ? STRINGS.unknown : text;
}

export function fractionText(value: number | null | undefined): string {
  if (value === null || value === undefined) return STRINGS.unknown;
  return `${Number((value * 100).toFixed(2))}%`;
}

export function priceVersionText(
  id: string | null | undefined,
  effective: string | null | undefined,
): string {
  return `price version ${orUnknown(id)} (effective ${orUnknown(effective)})`;
}
