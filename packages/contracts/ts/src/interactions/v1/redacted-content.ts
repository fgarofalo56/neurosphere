/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Which part of an interaction a piece of content is.
 *
 * This interface was referenced by `DetectionFinding`'s JSON-Schema
 * via the `definition` "part_kind".
 */
export type ContentPartKind =
  "prompt" | "response" | "tool_input" | "tool_output" | "system_instructions";
/**
 * Redacted text, 0 to 32768 characters, that matches none of the known credential formats (patterns are ECMA-262 compatible, no lookbehind). Mirrored by check_secret_free_text.
 *
 * This interface was referenced by `RedactedContent`'s JSON-Schema
 * via the `definition` "secret_free_text".
 */
export type SecretFreeText = string;
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
 * Redacted plaintext of one captured interaction (opt-in content capture, PRP-99): the document PRP-102 encrypts. It exists only in memory between redaction and encryption and after an audited decrypt; it is never an event, audit, index or notification field and no schema references it. Redaction replaces each detection with the placeholder `[[ns-redacted:<detected_category>]]`. Every text is secret-free: JSON Schema rejects text containing a private-key block, JWT, bearer token, AWS access key id, GitHub token, sk- key, Azure storage or Service Bus key assignment, SAS signature or URL with userinfo. The same patterns are mirrored by the Python validator check_secret_free_text in tests/contracts/validators.py, which PRP-101 must keep a subset of its credential detectors. redaction_state is `redacted` or `not_required` only; content whose redaction failed is not representable here. Pydantic ignores `not` (ADR-0004): validate against the JSON Schema before encryption.
 */
export interface RedactedContent {
  /**
   * Contract version of this document, major 1 with additive minor revisions.
   */
  schema_version: string;
  /**
   * Interaction this content belongs to (lowercase UUID).
   */
  interaction_id: string;
  /**
   * `redacted`: detectors ran and replaced detections. `not_required`: detectors ran and found nothing to replace. No other state is storable.
   */
  redaction_state: "redacted" | "not_required";
  /**
   * Version of the deterministic detector set that produced this redaction.
   */
  detector_set_version: string;
  /**
   * One part per ContentPartKind, at most five.
   *
   * @minItems 1
   * @maxItems 5
   */
  parts: [RedactedPart, ...RedactedPart[]];
}
/**
 * One redacted content part with its detection findings.
 *
 * This interface was referenced by `RedactedContent`'s JSON-Schema
 * via the `definition` "redacted_part".
 */
export interface RedactedPart {
  part: ContentPartKind;
  text: SecretFreeText;
  /**
   * True when the text was cut to the capture policy's max_part_chars.
   */
  truncated?: boolean;
  /**
   * Detector results for this part.
   *
   * @maxItems 256
   */
  findings?: DetectionFinding[];
}
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
