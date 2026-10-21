import {
  useInfiniteQuery,
  type InfiniteData,
  type UseInfiniteQueryResult,
} from "@tanstack/react-query";
import { useApiClient, type ApiError } from "../../api/index.js";
import type { ViewportResponse } from "./types";

/** The domain is the addressed resource (a path segment), never a client-supplied scope. */
export function viewportPath(domainId: string): string {
  return `/api/v1/map/domains/${encodeURIComponent(domainId)}/viewport`;
}

/** One viewport section: the top level (clusterId null) or one expanded cluster. */
export function useViewport(
  domainId: string,
  clusterId: string | null,
): UseInfiniteQueryResult<InfiniteData<ViewportResponse, string | undefined>, ApiError> {
  const client = useApiClient();
  return useInfiniteQuery<
    ViewportResponse,
    ApiError,
    InfiniteData<ViewportResponse, string | undefined>,
    unknown[],
    string | undefined
  >({
    queryKey: ["map-viewport", domainId, clusterId],
    initialPageParam: undefined,
    queryFn: ({ pageParam, signal }) => {
      const query: Record<string, string> = {};
      if (clusterId !== null) query["cluster_id"] = clusterId;
      if (pageParam !== undefined) query["cursor"] = pageParam;
      return client.get<ViewportResponse>(viewportPath(domainId), query, signal);
    },
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}
