/** Every label for the interaction explorer lives here so tests assert exact text. */
import type { InteractionRecord, PurposeCode } from "./types";

export const STRINGS = {
  title: "Interactions",
  description:
    "Captured AI interactions: metadata, detector findings and redaction state. Content stays encrypted; revealing it needs the time-bound interaction investigator role, a stated purpose, and is audited.",
  domainRequired: "Choose a domain to view its interactions.",
  domainLabel: "Interaction domain",
  filtersHeading: "Filters",
  filters: {
    agent: "Agent id",
    principal: "Principal id",
    tool: "Tool id",
    dataAsset: "Data asset id",
    category: "Detected category",
    from: "Captured from (UTC)",
    to: "Captured before (UTC)",
    any: "Any category",
    apply: "Apply filters",
    clear: "Clear filters",
    timeHint: "UTC, as YYYY-MM-DD or YYYY-MM-DDTHH:MM",
    timeInvalid: "Use YYYY-MM-DD or YYYY-MM-DDTHH:MM (UTC).",
  },
  listHeading: "Interaction list",
  noInteractions: "No interactions match these filters.",
  loading: "Loading...",
  loadMore: "Show more interactions",
  columns: {
    captured: "Captured",
    agent: "Agent",
    principal: "Principal",
    findings: "Findings",
    redaction: "Redaction",
    open: "Interaction",
  },
  openInteraction: "Inspect interaction",
  none: "none",
  notReported: "not reported",
  findingsCount: (n: number): string => (n === 1 ? "1 finding" : `${n} findings`),
  detail: {
    heading: (id: string): string => `Interaction ${id}`,
    captured: "Captured",
    occurred: "Occurred",
    source: "Capture source",
    agent: "Agent",
    tool: "Tool",
    principal: "Principal",
    model: "Model",
    dataAssets: "Data assets",
    parts: "Captured parts",
    redaction: "Redaction state",
    policy: "Capture policy",
    expires: "Content expires",
    legalHolds: "Legal holds",
    findingsHeading: "Detector findings",
    noFindings: "No detector findings.",
    findingAction: { replaced: "replaced", kept: "kept" },
    /** Detection covers structured identifiers only; never claim more. */
    coverageLabel: "Detection coverage: structured identifiers only",
    coverageNote:
      "Detectors match structured identifiers (credentials, card and account numbers, e-mail addresses and similar patterns). They do not judge free-text meaning, so content without findings can still be sensitive.",
    noContent: "No content was stored for this interaction, so there is nothing to reveal.",
  },
  redaction: {
    redacted: "Redacted",
    not_required: "Nothing to redact",
    redaction_failed: "Redaction failed: nothing stored",
  } satisfies Record<InteractionRecord["redaction_state"], string>,
  purposes: {
    incident_investigation: "Incident investigation",
    policy_violation_review: "Policy violation review",
    legal_hold_review: "Legal hold review",
    data_subject_request: "Data subject request",
    security_review: "Security review",
    quality_review: "Quality review",
  } satisfies Record<PurposeCode, string>,
  purpose: {
    label: "Purpose",
    placeholder: "Choose a purpose",
    required: "Choose a purpose before continuing.",
    caseRef: "Case reference (optional)",
    caseRefHint:
      "A case record id such as case-2026-0042: letters, digits and . _ : - only, at most 128 characters. GUIDs are refused because a directory object id is GUID-shaped and could identify a person.",
    caseRefInvalid: "Use letters, digits and . _ : - only (at most 128 characters).",
    caseRefGuid: "A GUID is refused as a case reference. Use your case record id instead.",
  },
  reveal: {
    open: "Reveal content",
    title: "Reveal interaction content",
    intro:
      "Reading content is recorded in the audit trail with your purpose and case reference before anything is decrypted. You see the stored redacted text only.",
    submit: "Reveal",
    close: "Close",
    revealing: "Revealing...",
    contentHeading: "Redacted content",
    truncated: "Truncated by the capture policy.",
    partFindings: "Findings in this part",
    notCached: "This content is not kept: closing the dialog discards it.",
  },
  exportFlow: {
    open: "Export content",
    title: "Export interaction content",
    intro:
      "An export bundles at most 500 interactions from this domain, is audited with your purpose, and expires after 24 hours. You may hold at most 5 open exports.",
    from: "Captured from (UTC)",
    to: "Captured before (UTC)",
    agent: "Agent id (optional)",
    category: "Detected category (optional)",
    rangeRequired: "Enter both ends of the time range (UTC).",
    submit: "Create export",
    creating: "Creating export...",
    close: "Close",
    manifestHeading: "Export manifest",
    exportId: "Export id",
    count: "Interactions in the bundle",
    ids: "Interaction ids listed",
    excluded: "Excluded (over the 500 limit or content already purged)",
    held: "Includes content under legal hold",
    expires: "Bundle expires",
    auditId: "Audit record",
    yes: "Yes",
    no: "No",
    download: "Download bundle",
    downloading: "Downloading...",
    downloaded: "Bundle downloaded. The download was recorded in the audit trail.",
  },
  errors: {
    forbiddenTitle: "You cannot read interaction content",
    forbidden:
      "Revealing or exporting content needs the time-bound interaction_investigator role in this domain, granted by an administrator (it expires within 7 days), plus a viewer assignment in the same domain. Administrators do not hold this permission themselves.",
    purposeInvalid:
      "The purpose was refused. Choose one of the listed purposes and check the case reference.",
    invalid: "The request was refused as invalid.",
    explorerUnconfiguredTitle: "Interaction explorer not configured",
    explorerUnconfigured:
      "This deployment has no interaction explorer: content capture is opt-in and is not configured here. An administrator can enable capture and the explorer.",
    exportUnconfigured: "Interaction exports are not configured in this deployment.",
    auditUnavailable:
      "The audit trail could not record this access, so nothing was decrypted. Try again later.",
    unavailable: "The service is unavailable. Try again later.",
    purged: "The content of this interaction has already been purged by retention.",
    notFound: "No such interaction.",
    exportEmpty: "No interactions match the export filters.",
    exportTooBroad: "The selection is too broad. Narrow the time range or the filters.",
    exportFiltersInvalid: "The export filters are invalid: the start must be before the end.",
    exportNotOwned: "Only the investigator who created an export can open it.",
    exportExpired: "This export has expired and was deleted.",
    limitReached: (wait: string): string =>
      `You already hold 5 open exports. The limit lifts when the oldest one expires, in about ${wait}.`,
    limitTitle: "Export limit reached",
    limitReachedNoWait:
      "You already hold 5 open exports. The limit lifts when the oldest one expires.",
    loadFailed: (what: string): string => `Could not load ${what}`,
    generic: (reference: string): string =>
      `The request failed${reference}. This is not an empty result.`,
  },
} as const;

export function purposeLabel(code: string): string {
  return (STRINGS.purposes as Record<string, string>)[code] ?? code;
}

export function redactionLabel(state: string): string {
  return (STRINGS.redaction as Record<string, string>)[state] ?? state;
}

/** "about 2 hours" style text for a Retry-After wait. */
export function waitText(seconds: number): string {
  if (seconds < 90) return `${Math.max(1, Math.round(seconds))} seconds`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes} minutes`;
  const hours = Math.round(minutes / 60);
  return hours === 1 ? "1 hour" : `${hours} hours`;
}
