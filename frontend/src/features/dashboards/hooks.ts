import { createQueryHook } from "../../api/index.js";
import type { DashboardParams, DashboardResponse } from "./types";

/**
 * The shared client refuses `domain_id` in its `query` option (scope keys are normally derived
 * server-side). The dashboards contract requires an explicit single domain_id that the server
 * authorizes, so it is encoded in the path here.
 */
export function dashboardPath(p: DashboardParams): string {
  const qs = new URLSearchParams({
    domain_id: p.domainId,
    days: String(p.days),
    grain: p.grain,
  });
  return `/api/v1/dashboards/${p.metric}?${qs.toString()}`;
}

export const useDashboard = createQueryHook<DashboardParams, DashboardResponse>({
  key: "dashboard",
  fetcher: (client, params, signal) =>
    client.get<DashboardResponse>(dashboardPath(params), undefined, signal),
});
