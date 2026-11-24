import { keepPreviousData, useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useApiClient, type ApiClient, type ApiError } from "../../../api/index.js";
import type { ImpactRequest, ImpactResponse } from "../types";

/** The map asks for two levels by default; the server default is three, its range 1 to 5. */
export const DEFAULT_IMPACT_DEPTH = 2;
export const MIN_IMPACT_DEPTH = 1;
export const MAX_IMPACT_DEPTH = 5;

export function impactPath(domainId: string): string {
  return `/api/v1/map/domains/${encodeURIComponent(domainId)}/impact`;
}

export function clampDepth(depth: number): number {
  if (!Number.isFinite(depth)) return DEFAULT_IMPACT_DEPTH;
  return Math.min(MAX_IMPACT_DEPTH, Math.max(MIN_IMPACT_DEPTH, Math.trunc(depth)));
}

export function fetchImpact(
  client: ApiClient,
  domainId: string,
  nodeId: string,
  depth: number,
  signal?: AbortSignal,
): Promise<ImpactResponse> {
  // The domain is the path segment, never a body field; the server derives scope.
  const body: ImpactRequest = { node_id: nodeId, max_depth: clampDepth(depth) };
  return client.post<ImpactResponse>(impactPath(domainId), body, signal);
}

/**
 * Dependents of one node (what relies on it) on the map route. Idle while `nodeId` is null. The
 * previous answer stays while a new depth loads, so the list never blanks; `refetch()` recomputes
 * for the incident view.
 */
export function useMapImpact(
  domainId: string,
  nodeId: string | null,
  depth: number = DEFAULT_IMPACT_DEPTH,
): UseQueryResult<ImpactResponse, ApiError> {
  const client = useApiClient();
  const clamped = clampDepth(depth);
  return useQuery<ImpactResponse, ApiError>({
    queryKey: ["map-impact", domainId, nodeId, clamped],
    queryFn: ({ signal }) => fetchImpact(client, domainId, nodeId ?? "", clamped, signal),
    enabled: nodeId !== null,
    placeholderData: keepPreviousData,
    // An incident answer is never reused from the cache after it was left: always ask again.
    gcTime: 0,
  });
}
