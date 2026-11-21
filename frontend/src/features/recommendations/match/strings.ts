/** Every user-visible string for Find an agent lives here so tests assert exact values. */
import type { PartialReason, SignalName } from "./types";

export const MATCH_STRINGS = {
  title: "Find an agent",
  taskLabel: "Describe the task",
  submit: "Find",
  submitting: "Searching...",
  accept: "Accept",
  reject: "Reject",
  accepted: "Accepted",
  rejected: "Rejected",
  changeDecision: "Change decision",
  noTelemetry: "No telemetry yet",
  coldStart: "Cold start: ranked on declared capabilities and tags only",
  partialResults: "Partial results",
  unobservedSignals: "Signals not observed",
  unobservedDetail: "These signals had no data and did not affect the ranking.",
  emptyState: "No agents or tools match. Try broader wording, or choose a domain filter.",
  domainRequired: "Choose a domain to find an agent.",
  forbidden: "You do not have access to this domain",
  failed: "Could not complete the search",
  feedbackFailed: "Could not record the decision",
  loading: "Loading...",
  confidenceLabel: "Confidence",
  confidenceNote:
    "Confidence reflects how much observed evidence backs a ranking. It is not a probability of success.",
  openInCatalog: "Open in catalog",
  showOnMap: "Show on map",
  taskHint: "Task text stays in this page only; it is not stored or put in the address.",
  resultsLabel: "Matching agents and tools",
  notAvailable: "Not available",
  score: "Score",
  kind: { agent: "Agent", tool: "Tool" },
  coldStartLabel: "Cold start",
  decisionLabel: "Decision",
  noDecision: "No decision yet",
  matchedCapabilities: "Matched capabilities",
  matchedTags: "Matched tags",
  relationships: "Graph relationships",
  noneText: "None",
  partialBanner: "Results are partial.",
  coldStartBanner: "Some signals have no observations yet",
  reasonCode: "Reason code",
  explanation: {
    caption: "How this candidate was ranked",
    signal: "Signal",
    observed: "Observed",
    weight: "Weight",
    contribution: "Contribution",
    observedValue: "Observed",
    notCounted: "Not counted",
  },
  metrics: {
    title: "Match outcomes",
    matches: "Matches",
    accepts: "Accepts",
    rejects: "Rejects",
    acceptanceRate: "Acceptance rate",
    noFeedback: "No feedback yet",
    outcomeNote: "The acceptance rate is an outcome to observe, not a target that has been met.",
    unavailable: "Match outcomes are unavailable",
    section: "Match outcomes and catalog completeness",
  },
  completeness: {
    title: "Catalog completeness",
    notAvailable: "Not available",
  },
} as const;

export const PARTIAL_REASON_LABELS: Record<PartialReason, string> = {
  limit: "Result limit reached; more candidates exist",
  timeout_ms: "Time budget reached; ranking may be incomplete",
};

export const SIGNAL_LABELS: Record<SignalName, string> = {
  capability_match: "Capability match",
  tag_match: "Tag match",
  text_match: "Text match",
  graph_proximity: "Graph proximity",
  historical_success: "Historical success",
  latency: "Latency",
  usage: "Usage",
  feedback_prior: "Feedback prior",
};

/** Live-region text for the result count. */
export function resultCountText(count: number): string {
  if (count === 0) return "No results";
  return count === 1 ? "1 result" : `${count} results`;
}
