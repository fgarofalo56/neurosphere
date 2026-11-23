/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Kind of sensitive content a detector found; open-ended: readers must tolerate unknown values. The first eight are credential categories (CredentialCategory).
 *
 * This interface was referenced by `DetectionFinding`'s JSON-Schema
 * via the `definition` "detected_category".
 */
export type DetectedCategory =
  | "private_key"
  | "jwt"
  | "bearer_token"
  | "cloud_access_key"
  | "vendor_api_key"
  | "connection_string"
  | "url_with_credentials"
  | "password_assignment"
  | "payment_card"
  | "iban"
  | "us_ssn"
  | "email_address"
  | "phone_number"
  | "ip_address"
  | "mac_address"
  | "guid"
  | "customer_dictionary_term"
  | "customer_identifier_pattern"
  | "other";
/**
 * Which part of an interaction a piece of content is.
 *
 * This interface was referenced by `DetectionFinding`'s JSON-Schema
 * via the `definition` "part_kind".
 */
export type ContentPartKind =
  "prompt" | "response" | "tool_input" | "tool_output" | "system_instructions";
/**
 * Categories that are credentials. Closed set: always replaced, never kept, and never listed in a capture policy's kept categories.
 *
 * This interface was referenced by `DetectionFinding`'s JSON-Schema
 * via the `definition` "credential_category".
 */
export type CredentialCategory =
  | "private_key"
  | "jwt"
  | "bearer_token"
  | "cloud_access_key"
  | "vendor_api_key"
  | "connection_string"
  | "url_with_credentials"
  | "password_assignment";

/**
 * One detector result for one content part of an interaction (opt-in content capture, PRP-99). A fragment: it has no schema_version of its own and is embedded by RedactedContent (and, in later items, the interaction record). It carries a category, counts and offsets into the redacted text, never the matched text. Rule JSON Schema expresses with if/then: a credential category (CredentialCategory) requires action `replaced`; a credential can never be kept. Pydantic ignores if/then (ADR-0004), so consumers validate against the JSON Schema.
 */
export interface DetectionFinding {
  category: DetectedCategory;
  part: ContentPartKind;
  /**
   * Detector that produced the finding (lowercase slug).
   */
  detector_id: string;
  /**
   * Detector version, semantic version without prefix.
   */
  detector_version: string;
  /**
   * Number of matches of this category in the part.
   */
  count: number;
  /**
   * What redaction did with the matches: `replaced` with a placeholder, or `kept` as written (only for non-credential categories a capture policy keeps).
   */
  action: "replaced" | "kept";
  /**
   * Detector confidence.
   */
  confidence: "high" | "medium" | "low";
  /**
   * Character offsets of the matches into the redacted text of the part. Offsets only; never the matched text.
   *
   * @maxItems 64
   */
  spans?: {
    start: number;
    end: number;
  }[];
}
