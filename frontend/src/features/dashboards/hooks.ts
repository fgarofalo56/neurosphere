import { createQueryHook } from "../../api/index.js";
import type { DashboardParams, DashboardResponse } from "./types";

/**
 * The domain is the addressed resource (a path segment), not a scope claim: the shared client
 * refuses `domain_id`/`customer_id` as parameters, and the server authorizes the domain against
 * the derived IdentityScope (403 when outside it).
 */
export function dashboardPath(p: DashboardParams): string {
  return `/api/v1/dashboards/domains/${encodeURIComponent(p.domainId)}/${p.metric}`;
}

export const useDashboard = createQueryHook<DashboardParams, DashboardResponse>({
  key: "dashboard",
  fetcher: (client, params, signal) =>
    client.get<DashboardResponse>(
      dashboardPath(params),
      { days: params.days, grain: params.grain },
      signal,
    ),
});
