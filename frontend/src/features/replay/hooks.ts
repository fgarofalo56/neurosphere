import {
  useInfiniteQuery,
  type InfiniteData,
  type UseInfiniteQueryResult,
} from "@tanstack/react-query";
import { createQueryHook, useApiClient, type ApiError } from "../../api/index.js";
import type { TraceDetail, TracePage } from "./types";

/**
 * GET-only typed fetch helpers. The domain is the addressed resource (a path segment), never a
 * scope parameter; the server authorizes it against the derived IdentityScope.
 */
export function tracesPath(domainId: string): string {
  return `/api/v1/replay/domains/${encodeURIComponent(domainId)}/traces`;
}

export function tracePath(domainId: string, traceId: string): string {
  return `${tracesPath(domainId)}/${encodeURIComponent(traceId)}`;
}

export interface TraceParams {
  readonly domainId: string;
  readonly traceId: string;
}

export const useTrace = createQueryHook<TraceParams, TraceDetail>({
  key: "replay-trace",
  fetcher: (client, p, signal) =>
    client.get<TraceDetail>(tracePath(p.domainId, p.traceId), undefined, signal),
});

export function useTraceList(
  domainId: string,
): UseInfiniteQueryResult<InfiniteData<TracePage, string | undefined>, ApiError> {
  const client = useApiClient();
  return useInfiniteQuery<
    TracePage,
    ApiError,
    InfiniteData<TracePage, string | undefined>,
    unknown[],
    string | undefined
  >({
    queryKey: ["replay-traces", domainId],
    initialPageParam: undefined,
    queryFn: ({ pageParam, signal }) =>
      client.get<TracePage>(
        tracesPath(domainId),
        pageParam === undefined ? { page_size: 25 } : { page_size: 25, cursor: pageParam },
        signal,
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}
