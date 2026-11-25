import type { CapturePolicyState } from "./types";

/** Why capture is off, in plain words. Keys are the API's reason codes. */
export const OFF_REASON_TEXT: Readonly<Record<string, string>> = {
  capture_not_configured: "Interaction capture is not set up in this deployment.",
  setting_off: "The deployment-wide interaction capture setting is off.",
  retention_not_enabled:
    "The retention policy does not allow keeping prompt and response content.",
  policy_limit_exceeded:
    "There are more capture policies than the service can load, so capture stays off.",
  no_policy: "No capture policy exists.",
  not_approved: "No capture policy is active with an approval.",
  source_mismatch: "No active policy names the source the data came from.",
  domain_missing: "The event carries no domain, so it is never captured.",
  domain_mismatch: "No active policy covers this domain.",
  not_sampled: "Sampling left this event out.",
  startup_pending: "Capture is starting; the policies have not been read yet.",
  ingest_disabled: "The ingest edge is not running, so there is nothing to capture from.",
  customer_unconfigured: "The customer is not configured.",
  audit_unavailable: "The audit store is not available, and capture needs it.",
  capture_env_invalid: "A capture setting in the environment is not valid.",
  capture_settings_invalid: "The interaction capture setting is not valid.",
  key_vault_not_configured: "No content encryption key is configured.",
  key_host_refused: "The content encryption key is in a vault this cloud does not allow.",
  key_wrap_unavailable: "The content encryption key cannot be used.",
  local_key_not_allowed: "A local development key is not allowed outside local runs.",
  local_key_file_missing: "The local development key file is missing.",
  blob_not_configured: "No content storage is configured.",
  cosmos_unconfigured: "The metadata store is not configured.",
  policy_store_unavailable: "The capture policies could not be read at startup.",
  capture_build_error: "Capture could not be set up.",
};

export function offReasonText(code: string): string {
  return OFF_REASON_TEXT[code] ?? "Interaction capture is off.";
}

export const CAPTURE_STRINGS = {
  title: "Interaction capture",
  description:
    "Capture policies and capture status. This page shows policy settings and counters only: never prompt or response content, and never key material.",
  changeNote:
    "This page is read-only. A change to a capture policy is proposed as a capture_policy_change action, approved by a second steward, and executes once PRP-108 ships.",
  statusTitle: "Status",
  policiesTitle: "Capture policies",
  detailTitle: "Policy detail",
  countersTitle: "Counters",
  loadingStatus: "Loading capture status",
  loadingPolicies: "Loading capture policies",
  loadingPolicy: "Loading the policy",
  panelDenied: "Access to this panel was denied by the service.",
  active: "Capture is on.",
  off: "Capture is off.",
  offReason: "Reason",
  noPolicies: "No capture policies.",
  noPoliciesHint: "Capture stays off until an approved policy is active.",
  notConfigured: "Interaction capture is not set up in this deployment.",
  truncated: "Only the first policies are shown.",
  noCounters: "No counters yet: capture has not started in this deployment.",
  closeDetail: "Close detail",
  view: "View",
  none: "None",
  policyCounts: (c: {
    total: number;
    active: number;
    proposed: number;
    suspended: number;
    retired: number;
  }): string =>
    `${c.total} policies: ${c.active} active, ${c.proposed} proposed, ${c.suspended} suspended, ${c.retired} retired.`,
  sampling: (rate: number, perMinute: number): string =>
    `${Math.round(rate * 1000) / 10}% of events, at most ${perMinute} per minute`,
  retention: (days: number | null, cls: string): string =>
    `${days === null ? "default" : `${days} days`} (${cls})`,
  state: {
    proposed: "Proposed",
    active: "Active",
    suspended: "Suspended",
    retired: "Retired",
  } satisfies Record<CapturePolicyState, string>,
  headers: {
    name: "Policy",
    domain: "Domain",
    sources: "Sources",
    parts: "Parts",
    redaction: "Redaction mode",
    sampling: "Sampling",
    state: "State",
    version: "Version",
    approval: "Approval audit id",
    actions: "Actions",
  },
  fields: {
    policyId: "Policy id",
    displayName: "Name",
    domain: "Domain",
    sources: "Source ids",
    parts: "Parts",
    detectorSet: "Detector set",
    dictionaries: "Customer dictionaries",
    redaction: "Redaction mode",
    kept: "Kept categories",
    sampling: "Sampling",
    maxPartChars: "Characters kept per part",
    retention: "Retention",
    state: "State",
    version: "Version",
    previousVersion: "Previous version",
    approvedIntent: "Approved intent id",
    approvedAudit: "Approval audit id",
    effectiveFrom: "Effective from",
  },
  counters: {
    captured: "Captured",
    skippedNoPolicy: "Skipped (no matching policy)",
    skippedItemCap: "Skipped (per-request limit)",
    failed: "Failed",
    shed: "Shed under load",
    auditWriteFailed: "Audit write failed",
    inFlight: "In flight",
    failedByReason: "Failed by reason",
    skippedByReason: "Skipped by reason",
    shedByReason: "Shed by reason",
  },
} as const;
