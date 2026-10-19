import type { Recommendation } from "@neurosphere/contracts";

export type { Recommendation };
export type Coverage = Recommendation["coverage"];
export type Owner = Recommendation["owner"];
export type Prerequisite = Recommendation["prerequisites"][number];
export type Uncertainty = Recommendation["uncertainty"];
export type ProjectedEstimate = NonNullable<Recommendation["projected_estimate"]>;

export type RecommendationKind = Recommendation["kind"];

export const RECOMMENDATION_KINDS: readonly RecommendationKind[] = [
  "cost_spike",
  "latency_degradation",
  "error_rate_degradation",
  "unused_agent",
  "candidate_duplicate",
  "model_right_sizing",
];

/** GET /api/v1/recommendations/domains/{domain}. */
export interface RecommendationListResponse {
  readonly items: readonly Recommendation[];
  readonly next_cursor: string | null;
}

export interface ReviewState {
  readonly state: "not_routed" | "pending_review";
  readonly review_request_id: string | null;
}

export interface ExecutionState {
  readonly executable: boolean;
  readonly reason: string;
}

/** GET /api/v1/recommendations/domains/{domain}/items/{recommendation_id}. */
export interface RecommendationDetailResponse {
  readonly recommendation: Recommendation;
  readonly review: ReviewState;
  readonly execution: ExecutionState;
}

/** POST /api/v1/recommendations/domains/{domain}/review-requests (202). */
export interface ReviewRequestResponse {
  readonly review_request_id: string;
  readonly state: "pending_review";
}

export interface ListParams {
  readonly domainId: string;
  readonly kind: RecommendationKind | "";
  readonly q: string;
  readonly cursor: string;
  readonly limit: number;
}

export interface DetailParams {
  readonly domainId: string;
  readonly recommendationId: string;
}

export interface ReviewVars {
  readonly domainId: string;
  readonly recommendationId: string;
}
