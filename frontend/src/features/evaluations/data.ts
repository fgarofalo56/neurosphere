import { useInfiniteQuery } from "@tanstack/react-query";
import { useApiClient, type ApiError } from "../../api/index.js";
import { evaluationResultsPath } from "./paths";
import type { EvaluationResultsPage } from "./types";

/** Results per request (the API allows more; the UI keeps pages short). */
export const EVALUATION_PAGE_SIZE = 20;

export interface EvaluationFilters {
  readonly subjectId: string;
  readonly dimension: string;
}

/** Cursor-paged results; the next cursor is the server's. The domain is a path segment only. */
export function useEvaluationResults(domain: string, filters: EvaluationFilters) {
  const client = useApiClient();
  return useInfiniteQuery<
    EvaluationResultsPage,
    ApiError,
    readonly EvaluationResultsPage[],
    unknown[],
    string | undefined
  >({
    queryKey: ["evaluation-results", domain, filters],
    enabled: domain !== "",
    initialPageParam: undefined,
    queryFn: ({ pageParam, signal }) =>
      client.get<EvaluationResultsPage>(
        evaluationResultsPath(domain),
        {
          limit: EVALUATION_PAGE_SIZE,
          ...(filters.subjectId === "" ? {} : { subject_id: filters.subjectId }),
          ...(filters.dimension === "" ? {} : { dimension: filters.dimension }),
          ...(pageParam === undefined ? {} : { cursor: pageParam }),
        },
        signal,
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    select: (data) => data.pages,
  });
}
