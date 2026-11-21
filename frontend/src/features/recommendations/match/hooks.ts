import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, createMutationHook, createQueryHook, useApiClient } from "../../../api/index.js";
import type {
  AgentMatchView,
  FeedbackAccepted,
  FeedbackVars,
  MatchCompleteness,
  MatchCompletenessData,
  MatchMetricsView,
  MatchParams,
  MatchVars,
} from "./types";

/**
 * The domain is the addressed resource (a path segment), not a scope claim: the shared client
 * refuses `domain_id`/`customer_id` as parameters or body keys, and the server authorizes the
 * domain against the derived IdentityScope.
 */
export function matchPath(domainId: string): string {
  return `/api/v1/recommendations/domains/${encodeURIComponent(domainId)}/match`;
}

export function matchFeedbackPath(domainId: string): string {
  return `${matchPath(domainId)}/feedback`;
}

export function matchMetricsPath(domainId: string): string {
  return `${matchPath(domainId)}/metrics`;
}

export const COMPLETENESS_PATH = "/api/v1/catalog/completeness";

export const METRICS_QUERY_KEY = "match-metrics";

export const useAgentMatch = createMutationHook<MatchVars, AgentMatchView>({
  mutate: (client, v) => client.post<AgentMatchView>(matchPath(v.domainId), v.request),
});

export const useMatchMetrics = createQueryHook<MatchParams, MatchMetricsView>({
  key: METRICS_QUERY_KEY,
  fetcher: (client, p, signal) =>
    client.get<MatchMetricsView>(matchMetricsPath(p.domainId), undefined, signal),
});

/** Feedback mutation; a success refetches the metrics strip so accept counts stay current. */
export function useMatchFeedback() {
  const client = useApiClient();
  const queryClient = useQueryClient();
  return useMutation<FeedbackAccepted, ApiError, FeedbackVars>({
    mutationFn: (v) => client.post<FeedbackAccepted>(matchFeedbackPath(v.domainId), v.request),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [METRICS_QUERY_KEY] }),
  });
}

/** 404 or capability_unavailable means PRP-76 is not there: absent. Other errors stay errors. */
export function isCompletenessAbsent(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  // The shared client maps every 5xx to dependency_transient, so a 503 problem body that says
  // capability_unavailable is only visible on `error.problem`.
  return (
    error.status === 404 ||
    error.code === "capability_unavailable" ||
    error.problem?.code === "capability_unavailable"
  );
}

export const useMatchCompleteness = createQueryHook<Record<string, never>, MatchCompleteness>({
  key: "match-completeness",
  fetcher: async (client, _p, signal) => {
    try {
      const data = await client.get<MatchCompletenessData>(COMPLETENESS_PATH, undefined, signal);
      return { state: "present", data };
    } catch (error) {
      if (isCompletenessAbsent(error)) return { state: "absent" };
      throw error;
    }
  },
});
