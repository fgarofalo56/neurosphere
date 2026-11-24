import { createQueryHook } from "../../../api/index.js";
import type { SearchCounts, SearchResponse } from "../types";

export function searchPath(domainId: string): string {
  return `/api/v1/map/domains/${encodeURIComponent(domainId)}/search`;
}

export interface FilterCountsParams {
  readonly domainId: string;
}

const EMPTY_COUNTS: SearchCounts = {
  by_kind: {},
  by_health: {},
  by_environment: {},
  by_cloud: {},
};

/**
 * Option lists come from the search route `counts` (they cover every match scanned, not only the
 * returned page). An empty query with `limit=1` is the cheapest call that returns them; no filters
 * are sent so the option list stays stable while the user narrows the map.
 */
export const useFilterCounts = createQueryHook<FilterCountsParams, SearchResponse>({
  key: "map-filter-counts",
  fetcher: (client, params, signal) =>
    client.get<SearchResponse>(searchPath(params.domainId), { q: "", limit: 1 }, signal),
});

/** Tolerates a response without counts (an older server) as "no options". */
export function countsOf(data: SearchResponse | undefined): SearchCounts {
  const c = (data as { counts?: Partial<SearchCounts> } | undefined)?.counts;
  if (c === undefined) return EMPTY_COUNTS;
  return {
    by_kind: c.by_kind ?? {},
    by_health: c.by_health ?? {},
    by_environment: c.by_environment ?? {},
    by_cloud: c.by_cloud ?? {},
  };
}
