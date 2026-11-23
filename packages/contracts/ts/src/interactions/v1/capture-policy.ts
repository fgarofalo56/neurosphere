/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Which part of an interaction a piece of content is.
 */
export type ContentPartKind =
  "prompt" | "response" | "tool_input" | "tool_output" | "system_instructions";
/**
 * Kind of sensitive content a detector found; open-ended: readers must tolerate unknown values. The first eight are credential categories (CredentialCategory).
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
 * Opt-in capture policy per domain and source (PRP-99; container interaction_capture_policies, declared by PRP-102). Capture is off unless an active policy exists. kept_categories can never hold a credential category and an active policy requires approved_intent_id and approved_audit_id; both rules are JSON Schema (`not`, if/then) that Pydantic ignores (ADR-0004), so consumers validate against the JSON Schema.
 */
export interface CapturePolicy {
  /**
   * Contract version of this document, major 1 with additive minor revisions.
   */
  schema_version: string;
  /**
   * Capture policy id (slug).
   */
  capture_policy_id: string;
  /**
   * Policy version, increments on every change.
   */
  version: number;
  /**
   * Version this one replaces. Null for the first.
   */
  previous_version?: number | null;
  /**
   * Console label.
   */
  display_name: string;
  /**
   * Sovereign cloud boundary.
   */
  cloud: "commercial" | "government";
  /**
   * Customer segment.
   */
  customer_id: string;
  /**
   * Domain the policy applies to.
   */
  domain_id: string;
  /**
   * Sources capture is turned on for.
   *
   * @minItems 1
   * @maxItems 64
   *
   * Items: Lowercase identifier token (source IDs, platforms, providers, kinds).
   */
  source_ids: [string, ...string[]];
  /**
   * Parts that may be captured.
   *
   * @minItems 1
   * @maxItems 5
   */
  parts: [ContentPartKind, ...ContentPartKind[]];
  /**
   * Deterministic detector set that redacts.
   */
  detector_set_version: string;
  /**
   * Customer dictionaries applied.
   *
   * @maxItems 16
   *
   * Items: Lowercase operator-chosen identifier.
   */
  customer_dictionary_ids?: string[];
  /**
   * `redact_all_detections` (default, GD-4) or `redact_listed`.
   */
  redaction_mode?: "redact_all_detections" | "redact_listed";
  /**
   * Non-credential categories kept as written. Never a credential category (CredentialCategory): credentials are always redacted.
   */
  kept_categories?: DetectedCategory[];
  /**
   * Sampling limits.
   */
  sampling: {
    /**
     * Fraction of interactions captured, above 0 up to 1.
     */
    rate: number;
    max_per_minute: number;
  };
  /**
   * Characters kept per part; the rest is truncated.
   */
  max_part_chars?: number;
  /**
   * Retention class (slug).
   */
  retention_class: string;
  /**
   * Days captured content is kept (GD-5); legal hold overrides.
   */
  retention_days?: number;
  /**
   * `proposed` until an approved capture_policy_change activates it.
   */
  state: "proposed" | "active" | "suspended" | "retired";
  /**
   * Approved action intent. Required (non-null) when active.
   */
  approved_intent_id?: string | null;
  /**
   * Audit record of the approval. Required (non-null) when active.
   */
  approved_audit_id?: string | null;
  /**
   * When the policy took effect. Null until activated.
   */
  effective_from?: string | null;
}
