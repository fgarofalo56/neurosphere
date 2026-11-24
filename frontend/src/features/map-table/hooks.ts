import {
  useInfiniteQuery,
  type InfiniteData,
  type UseInfiniteQueryResult,
} from "@tanstack/react-query";
import { useApiClient, type ApiError } from "../../api/index.js";
import type { MapFilterQuery } from "../map/filters/useMapFilters";
import type { ViewportResponse } from "./types";

const NO_FILTERS: MapFilterQuery = {};

/** The domain is the addressed resource (a path segment), never a client-supplied scope. */
export function viewportPath(domainId: string): string {
  return `/api/v1/map/domains/${encodeURIComponent(domainId)}/viewport`;
}

/**
 * One viewport section: the top level (clusterId null) or one expanded cluster. The active map
 * filters (the same URL state as the map) are sent as the PRP-74 query parameters and key the
 * cache.
 */
export function useViewport(
  domainId: string,
  clusterId: string | null,
  filters: MapFilterQuery = NO_FILTERS,
): UseInfiniteQueryResult<InfiniteData<ViewportResponse, string | undefined>, ApiError> {
  const client = useApiClient();
  return useInfiniteQuery<
    ViewportResponse,
    ApiError,
    InfiniteData<ViewportResponse, string | undefined>,
    unknown[],
    string | undefined
  >({
    queryKey: ["map-viewport", domainId, clusterId, filters],
    initialPageParam: undefined,
    queryFn: ({ pageParam, signal }) => {
      const query: Record<string, string> = { ...filters };
      if (clusterId !== null) query["cluster_id"] = clusterId;
      if (pageParam !== undefined) query["cursor"] = pageParam;
      return client.get<ViewportResponse>(viewportPath(domainId), query, signal);
    },
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}
