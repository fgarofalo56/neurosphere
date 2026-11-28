import { ForbiddenError, type ApiError } from "../../api/index.js";
import { STRINGS, waitText } from "./strings";

/**
 * Maps an API failure of the explorer to the text the page shows. The shared client turns every
 * 5xx into `dependency_transient`; the specific cause is the problem body's `reason` (for example
 * `interaction_explorer_unconfigured` or `audit_write_failed`), so the reason decides here, never
 * the class alone.
 */
export interface ProblemView {
  readonly kind: "forbidden" | "invalid" | "unavailable" | "not_found" | "limit" | "failed";
  readonly title: string;
  readonly message: string;
}

export const EXPLORER_UNCONFIGURED = "interaction_explorer_unconfigured";

export function reasonOf(error: ApiError): string | undefined {
  return error.problem?.reason;
}

function reference(error: ApiError): string {
  return error.correlationId !== "" ? ` (reference ${error.correlationId})` : "";
}

const NOT_FOUND_REASONS: Readonly<Record<string, string>> = {
  interaction_content_purged: STRINGS.errors.purged,
  interaction_not_found: STRINGS.errors.notFound,
  interaction_export_empty: STRINGS.errors.exportEmpty,
  interaction_export_expired: STRINGS.errors.exportExpired,
  interaction_export_not_found: STRINGS.errors.notFound,
};

const INVALID_REASONS: Readonly<Record<string, string>> = {
  interaction_purpose_invalid: STRINGS.errors.purposeInvalid,
  interaction_export_selection_too_broad: STRINGS.errors.exportTooBroad,
  interaction_export_filters_invalid: STRINGS.errors.exportFiltersInvalid,
};

const UNAVAILABLE_REASONS: Readonly<Record<string, string>> = {
  [EXPLORER_UNCONFIGURED]: STRINGS.errors.explorerUnconfigured,
  interaction_export_unconfigured: STRINGS.errors.exportUnconfigured,
  audit_write_failed: STRINGS.errors.auditUnavailable,
};

/** For a content read or an export (the actions only an investigator may take). */
export function describeActionError(error: ApiError): ProblemView {
  const reason = reasonOf(error) ?? "";
  if (error instanceof ForbiddenError || error.status === 403) {
    const message =
      reason === "export_not_owned" ? STRINGS.errors.exportNotOwned : STRINGS.errors.forbidden;
    return { kind: "forbidden", title: STRINGS.errors.forbiddenTitle, message };
  }
  if (error.status === 422) {
    return {
      kind: "invalid",
      title: STRINGS.errors.invalid,
      message: INVALID_REASONS[reason] ?? STRINGS.errors.invalid,
    };
  }
  if (error.status === 429) {
    const wait = error.retryAfterSeconds;
    return {
      kind: "limit",
      title: STRINGS.errors.limitTitle,
      message:
        wait !== undefined
          ? STRINGS.errors.limitReached(waitText(wait))
          : STRINGS.errors.limitReachedNoWait,
    };
  }
  if (error.status === 404) {
    return {
      kind: "not_found",
      title: STRINGS.errors.notFound,
      message: NOT_FOUND_REASONS[reason] ?? STRINGS.errors.notFound,
    };
  }
  if (error.status >= 500 || error.code === "dependency_transient") {
    const title =
      reason === EXPLORER_UNCONFIGURED
        ? STRINGS.errors.explorerUnconfiguredTitle
        : STRINGS.errors.unavailable;
    return {
      kind: "unavailable",
      title,
      message: `${UNAVAILABLE_REASONS[reason] ?? STRINGS.errors.unavailable}${reference(error)}`,
    };
  }
  return {
    kind: "failed",
    title: STRINGS.errors.loadFailed("the result"),
    message: STRINGS.errors.generic(reference(error)),
  };
}
