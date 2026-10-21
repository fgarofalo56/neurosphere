import { useContext, useEffect, useRef, useState } from "react";
import { createQueryHook, type ApiClient } from "../../api/index.js";
import { ConfigContext } from "../../app/ConfigContext";
import { getToken } from "../../auth/token";
import { createLiveClient, realtimeUrl, type LiveStatus } from "./realtime";
import { NODE_BUDGET, type DeltaMessage, type ViewportResponse } from "./types";

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
      node_budget: budget,
      ...(params.clusterId !== undefined && { cluster_id: params.clusterId }),
      ...(params.cursor !== undefined && { cursor: params.cursor }),
    },
    signal,
  );
}

export const useViewport = createQueryHook<ViewportParams, ViewportResponse>({
  key: "map-viewport",
  fetcher: (client, params, signal) => fetchViewport(client, params, signal),
});

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
): LiveState {
  const config = useContext(ConfigContext);
  const [status, setStatus] = useState<LiveStatus>("connecting");
  const [lastErrorCode, setLastErrorCode] = useState<string | null>(null);
  const onDeltaRef = useRef(onDelta);
  onDeltaRef.current = onDelta;
  const apiBaseUrl = config?.apiBaseUrl ?? null;

  useEffect(() => {
    if (!enabled || domainId === "") return;
    if (apiBaseUrl === null) {
      setStatus("unavailable");
      return;
    }
    setLastErrorCode(null);
    const client = createLiveClient({
      url: realtimeUrl(apiBaseUrl),
      domainId,
      getToken,
      onStatus: setStatus,
      onDelta: (delta) => onDeltaRef.current(delta),
      onError: setLastErrorCode,
    });
    client.start();
    return () => client.stop();
  }, [apiBaseUrl, domainId, enabled]);

  return { status, lastErrorCode };
}
