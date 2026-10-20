import { createMutationHook, createQueryHook } from "../../api/index.js";
import type {
  DetailParams,
  ListParams,
  RecommendationDetailResponse,
  RecommendationListResponse,
  ReviewRequestResponse,
  ReviewVars,
} from "./types";

/**
 * The domain is the addressed resource (a path segment), not a scope claim: the shared client
 * refuses `domain_id`/`customer_id` as parameters, and the server authorizes the domain against
 * the derived IdentityScope (403 when outside it).
 */
export function listPath(domainId: string): string {
  return `/api/v1/recommendations/domains/${encodeURIComponent(domainId)}`;
}

export function detailPath(domainId: string, recommendationId: string): string {
  return `${listPath(domainId)}/items/${encodeURIComponent(recommendationId)}`;
}

export function reviewRequestsPath(domainId: string): string {
  return `${listPath(domainId)}/review-requests`;
}

export const useRecommendations = createQueryHook<ListParams, RecommendationListResponse>({
  key: "recommendations",
  fetcher: (client, p, signal) =>
    client.get<RecommendationListResponse>(
      listPath(p.domainId),
      {
        kind: p.kind === "" ? undefined : p.kind,
        q: p.q === "" ? undefined : p.q,
        cursor: p.cursor === "" ? undefined : p.cursor,
        limit: p.limit,
      },
      signal,
    ),
});

export const useRecommendation = createQueryHook<DetailParams, RecommendationDetailResponse>({
  key: "recommendation",
  fetcher: (client, p, signal) =>
    client.get<RecommendationDetailResponse>(
      detailPath(p.domainId, p.recommendationId),
      undefined,
      signal,
    ),
});

/** The only action on a recommendation: route it to review. There is no execute hook. */
export const useRouteToReview = createMutationHook<ReviewVars, ReviewRequestResponse>({
  mutate: (client, v) =>
    client.post<ReviewRequestResponse>(reviewRequestsPath(v.domainId), {
      recommendation_id: v.recommendationId,
    }),
});
