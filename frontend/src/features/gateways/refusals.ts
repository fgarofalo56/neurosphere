import { DependencyTransientError, ForbiddenError, type ApiError } from "../../api/index.js";
import { STRINGS } from "./strings";

const KNOWN_REASONS = [
  "gateway_mode_unchanged",
  "gateway_manage_unavailable",
  "gateway_applying",
  "gateway_observe_mode",
  "gateway_preflight_failed",
  "gateway_not_registered",
] as const;

export type RefusalReason = (typeof KNOWN_REASONS)[number];

/** The server's machine reason of a refusal, when it is one of the gateway refusal reasons. */
export function refusalReason(error: ApiError): RefusalReason | undefined {
  const reason = error.problem?.reason;
  return KNOWN_REASONS.find((known) => known === reason);
}

/**
 * Maps a refused gateway draft to a precise sentence. A Government refusal keeps the server's own
 * reason text (the capability-matrix note) because it differs per profile.
 */
export function gatewayRefusalText(error: ApiError): string {
  const R = STRINGS.refusals;
  const reason = refusalReason(error);
  if (reason === "gateway_manage_unavailable") {
    const detail = error.problem?.detail;
    return detail !== undefined && detail.trim() !== ""
      ? `${R.gateway_manage_unavailable} ${detail}`
      : R.gateway_manage_unavailable;
  }
  if (reason !== undefined) return R[reason];
  if (error instanceof ForbiddenError) return R.forbidden;
  if (error instanceof DependencyTransientError) return R.unavailable;
  return R.generic;
}
