import { createQueryHook } from "../../api/index.js";
import type { ReconciliationParams, ReconciliationResponse } from "./types";

/**
 * The domain is the addressed resource (a path segment), not a scope claim: the shared client
 * refuses `domain_id`/`customer_id` as parameters, and the server authorizes the domain against
 * the derived IdentityScope (403 when outside it).
 */
export function reconciliationPath(p: ReconciliationParams): string {
  return `/api/v1/reconciliation/domains/${encodeURIComponent(p.domainId)}`;
}

export const useReconciliation = createQueryHook<ReconciliationParams, ReconciliationResponse>({
  key: "reconciliation",
  fetcher: (client, params, signal) =>
    client.get<ReconciliationResponse>(reconciliationPath(params), { days: params.days }, signal),
});
