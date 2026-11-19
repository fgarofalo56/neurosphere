/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Canonical ID grammar cloud:customer:source:type:id. cloud is commercial or government; customer, source and type are lowercase [a-z0-9._-]; id is lowercase [a-z0-9._-] plus '/' and '='; no segment may contain ':'. Corpus: id-corpus.json. Python validator validate_canonical_id_fullmatch re-checks with re.fullmatch because Python re.search lets '$' match before a trailing newline.
 */
export type CanonicalId = string;

/**
 * A steward's accept or reject of one match candidate (PRP-70 item 3). Reason codes only: there is deliberately no free-text field, so no PII-bearing text is stored. reason_code is optional and defaults to null. Cloud, customer, domain and actor come from the server-derived IdentityScope, not the request.
 */
export interface AgentMatchFeedbackRequest {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  match_id: string;
  entity_id: CanonicalId;
  decision: "accepted" | "rejected";
  reason_code?:
    | ("not_relevant" | "missing_capability" | "poor_quality" | "unavailable" | "policy" | "other")
    | null;
}
