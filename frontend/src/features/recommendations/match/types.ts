import type {
  AgentMatchFeedbackRequest,
  AgentMatchRequest,
  AgentMatchResponse,
} from "@neurosphere/contracts";

export type { AgentMatchFeedbackRequest, AgentMatchRequest, AgentMatchResponse };
export type AgentMatchCandidate = AgentMatchResponse["candidates"][number];
export type AgentMatchSignal = AgentMatchCandidate["signals"][number];
export type SignalName = AgentMatchSignal["signal"];
export type FeedbackDecision = AgentMatchFeedbackRequest["decision"];
export type PartialReason = NonNullable<AgentMatchResponse["partial_reason"]>;

export const SIGNAL_NAMES: readonly SignalName[] = [
  "capability_match",
  "tag_match",
  "text_match",
  "graph_proximity",
  "historical_success",
  "latency",
  "usage",
  "feedback_prior",
];

/** services/api recommendations/match_models.py CandidateAssessment. */
export interface CandidateAssessment {
  readonly entity_id: string;
  readonly confidence: number;
  readonly cold_start: boolean;
}

/** The real 200 body of the match POST (PRP-72 AgentMatchView). */
export interface AgentMatchView {
  readonly match: AgentMatchResponse;
  readonly assessments: readonly CandidateAssessment[];
  readonly confidence_note: string;
}

/** 202 body of the feedback POST. */
export interface FeedbackAccepted {
  readonly match_id: string;
  readonly entity_id: string;
  readonly decision: FeedbackDecision;
  readonly decided_at: string;
}

/** GET .../match/metrics. acceptance_rate is null until feedback exists, never 0. */
export interface MatchMetricsView {
  readonly domain_id: string;
  readonly window_start: string;
  readonly window_end: string;
  readonly matches: number;
  readonly matches_with_feedback: number;
  readonly accepts: number;
  readonly rejects: number;
  readonly acceptance_rate: number | null;
}

/**
 * GET /api/v1/catalog/completeness (PRP-76, not built yet). Absent means the capability is not
 * there; present data is read defensively, every field optional.
 */
export interface MatchCompletenessData {
  readonly [key: string]: unknown;
  readonly ratio?: number | null;
}
export type MatchCompleteness =
  | { readonly state: "absent" }
  | { readonly state: "present"; readonly data: MatchCompletenessData };

export interface MatchParams {
  readonly domainId: string;
}
export interface MatchVars {
  readonly domainId: string;
  readonly request: AgentMatchRequest;
}
export interface FeedbackVars {
  readonly domainId: string;
  readonly request: AgentMatchFeedbackRequest;
}

export interface JoinedCandidate {
  readonly candidate: AgentMatchCandidate;
  /** Undefined when the server sent no assessment for this entity; never a fabricated 0. */
  readonly assessment: CandidateAssessment | undefined;
}

export function joinAssessments(view: AgentMatchView): JoinedCandidate[] {
  const byEntity = new Map<string, CandidateAssessment>();
  for (const a of view.assessments) byEntity.set(a.entity_id, a);
  return view.match.candidates.map((candidate) => ({
    candidate,
    assessment: byEntity.get(candidate.entity_id),
  }));
}
