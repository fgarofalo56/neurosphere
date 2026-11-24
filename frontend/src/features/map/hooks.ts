import { keepPreviousData, useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useContext, useEffect, useRef, useState } from "react";
import { useApiClient, type ApiClient, type ApiError } from "../../api/index.js";
import { ConfigContext } from "../../app/ConfigContext";
import { getToken } from "../../auth/token";
import type { MapFilterQuery } from "./filters/useMapFilters";
import { createLiveClient, realtimeUrl, type LiveStatus } from "./realtime";
import {
  NODE_BUDGET,
  type DeltaMessage,
  type TopologyMessage,
  type ViewportResponse,
} from "./types";

/**
 * The domain is the addressed resource (a path segment), never a scope parameter; the server
 * authorizes it against the derived IdentityScope and denies on mismatch.
 */
export function viewportPath(domainId: string): string {
  return `/api/v1/map/domains/${encodeURIComponent(domainId)}/viewport`;
}

export interface ViewportParams {
  readonly domainId: string;
  readonly clusterId?: string;
  readonly cursor?: string;
  /** Never above NODE_BUDGET; the server clamps as well. */
  readonly nodeBudget?: number;
  /** The active PRP-74 filters (node_type, tag, environment, cloud, health); each is single-valued. */
  readonly filters?: MapFilterQuery;
}

export function fetchViewport(
  client: ApiClient,
  params: ViewportParams,
  signal?: AbortSignal,
): Promise<ViewportResponse> {
  const budget = Math.max(1, Math.min(params.nodeBudget ?? NODE_BUDGET, NODE_BUDGET));
  return client.get<ViewportResponse>(
    viewportPath(params.domainId),
    {
      ...params.filters,
      node_budget: budget,
      ...(params.clusterId !== undefined && { cluster_id: params.clusterId }),
      ...(params.cursor !== undefined && { cursor: params.cursor }),
    },
    signal,
  );
}

/**
 * The first viewport page. The cache is keyed by the whole params object, so a changed filter is a
 * new request. The previous page stays as placeholder while the new one loads, so the toolbar and
 * canvas do not unmount (and the filter field keeps focus) on every filter change.
 */
export function useViewport(params: ViewportParams): UseQueryResult<ViewportResponse, ApiError> {
  const client = useApiClient();
  return useQuery<ViewportResponse, ApiError>({
    queryKey: ["map-viewport", params],
    queryFn: ({ signal }) => fetchViewport(client, params, signal),
    placeholderData: keepPreviousData,
  });
}

/** Quiet time after the last topology message before the map refetches. */
export const TOPOLOGY_DEBOUNCE_MS = 400;
/** A steady stream still refetches at least this often, inside the 5 s freshness target. */
export const TOPOLOGY_MAX_WAIT_MS = 2000;

export interface BurstDebouncer {
  /** Records one message; the work runs once after the burst goes quiet (or the max wait). */
  trigger(): void;
  cancel(): void;
}

/**
 * Collapses a burst of triggers into one call of `run`: trailing debounce with a maximum wait so
 * a continuous stream cannot starve the refetch. Pure (timers injected) so it is unit-testable.
 */
export function createBurstDebouncer(
  run: () => void,
  delayMs: number = TOPOLOGY_DEBOUNCE_MS,
  maxWaitMs: number = TOPOLOGY_MAX_WAIT_MS,
  setTimer: (cb: () => void, ms: number) => number = (cb, ms) => window.setTimeout(cb, ms),
  clearTimer: (handle: number) => void = (h) => window.clearTimeout(h),
): BurstDebouncer {
  let quiet: number | null = null;
  let ceiling: number | null = null;

  function clearAll(): void {
    if (quiet !== null) clearTimer(quiet);
    if (ceiling !== null) clearTimer(ceiling);
    quiet = null;
    ceiling = null;
  }

  function fire(): void {
    clearAll();
    run();
  }

  return {
    trigger() {
      if (quiet !== null) clearTimer(quiet);
      quiet = setTimer(fire, delayMs);
      ceiling ??= setTimer(fire, maxWaitMs);
    },
    cancel: clearAll,
  };
}

export interface LiveState {
  readonly status: LiveStatus;
  readonly lastErrorCode: string | null;
}

/**
 * Subscribes to the gateway for one domain while `enabled`. Without an app config (a bare test
 * tree) or without a reachable gateway the state is `unavailable`, never silently "live".
 */
export function useLiveUpdates(
  domainId: string,
  enabled: boolean,
  onDelta: (delta: DeltaMessage) => void,
  onTopology?: (topology: TopologyMessage) => void,
): LiveState {
  const config = useContext(ConfigContext);
  const [status, setStatus] = useState<LiveStatus>("connecting");
  const [lastErrorCode, setLastErrorCode] = useState<string | null>(null);
  const onDeltaRef = useRef(onDelta);
  // Set synchronously on the revoke close so a delta racing the close can never reach the map.
  const revokedRef = useRef(false);
  onDeltaRef.current = onDelta;
  const onTopologyRef = useRef(onTopology);
  onTopologyRef.current = onTopology;
  const apiBaseUrl = config?.apiBaseUrl ?? null;

  useEffect(() => {
    if (!enabled || domainId === "") return;
    if (apiBaseUrl === null) {
      setStatus("unavailable");
      return;
    }
    setLastErrorCode(null);
    revokedRef.current = false;
    const client = createLiveClient({
      url: realtimeUrl(apiBaseUrl),
      domainId,
      getToken,
      onStatus: (next) => {
        if (next === "revoked") revokedRef.current = true;
        setStatus(next);
      },
      onDelta: (delta) => {
        if (!revokedRef.current) onDeltaRef.current(delta);
      },
      onTopology: (topology) => {
        if (!revokedRef.current) onTopologyRef.current?.(topology);
      },
      onError: setLastErrorCode,
    });
    client.start();
    return () => client.stop();
  }, [apiBaseUrl, domainId, enabled]);

  return { status, lastErrorCode };
}
