/** Closed reason-code list of the deprecate and recertify bodies (PRP-31 item 9). */
export const REASON_CODES = [
  "superseded",
  "no_longer_used",
  "owner_changed",
  "owner_left",
  "security_issue",
  "quality_issue",
  "periodic_review",
  "other",
] as const;
export type ReasonCode = (typeof REASON_CODES)[number];
