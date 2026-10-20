import { createQueryHook } from "../../api/index.js";
import type { QualityParams, QualityResponse } from "./types";

/**
 * The domain is the addressed resource (a path segment), not a scope claim: the shared client
 * refuses `domain_id`/`customer_id` as parameters, and the server authorizes the domain against
 * the derived IdentityScope (403 when outside it).
 */
export function qualityPath(domainId: string): string {
  return `/api/v1/evaluation/domains/${encodeURIComponent(domainId)}/quality`;
}

export const useQuality = createQueryHook<QualityParams, QualityResponse>({
  key: "evaluation-quality",
  fetcher: (client, p, signal) =>
    client.get<QualityResponse>(
      qualityPath(p.domainId),
      { subject_id: p.subjectId === "" ? undefined : p.subjectId },
      signal,
    ),
});
