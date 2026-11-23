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
 * Which part of an interaction a piece of content is.
 */
export type ContentPartKind =
  "prompt" | "response" | "tool_input" | "tool_output" | "system_instructions";
/**
 * Which parts were captured and their sizes; sizes only, never text.
 *
 * @maxItems 5
 */
export type ContentParts = {
  part: ContentPartKind;
  char_count: number;
  truncated: boolean;
}[];
/**
 * Detected category.
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
 * Sensitivity categories the interaction touched.
 *
 * @maxItems 10
 *
 * Items: Kind of sensitive data a data asset holds; sits beside classification, not instead of it. Open-ended: readers must tolerate unknown values.
 */
export type SensitivityCategories = (
  | "pii"
  | "phi"
  | "cui"
  | "pci"
  | "financial"
  | "biometric"
  | "credentials"
  | "export_controlled"
  | "legal_privileged"
  | "other"
)[];

/**
 * Index document of one captured interaction (PRP-99; container interaction_index, declared by PRP-102). Metadata only: it has no content-bearing property, no string over 1024 characters, no hash of plaintext and references neither ContentEnvelope nor RedactedContent. The content lives encrypted behind content_ref (null when nothing was stored).
 */
export interface InteractionRecord {
  /**
   * Contract version of this document, major 1 with additive minor revisions.
   */
  schema_version: string;
  /**
   * Interaction identifier (lowercase UUID); joins payload_ref.interaction_id.
   */
  interaction_id: string;
  /**
   * Sovereign cloud boundary.
   */
  cloud: "commercial" | "government";
  /**
   * Customer segment.
   */
  customer_id: string;
  /**
   * Owning domain; authorization scope anchor.
   */
  domain_id: string;
  /**
   * Connector or producer that emitted the event.
   */
  source_id: string;
  /**
   * Source-assigned event id; with source_id it joins the TelemetryEvent.
   */
  event_id: string;
  /**
   * W3C trace id. Null when not traced.
   */
  trace_id?: string | null;
  /**
   * Span id. Null when not reported.
   */
  span_id?: string | null;
  /**
   * Correlation id shared with the audit and policy trail.
   */
  correlation_id: string;
  /**
   * How the interaction was captured: `edge_push`, `otlp_attributes`, `gateway_log` or `connector`. Open-ended: readers must tolerate unknown values.
   */
  capture_source: "edge_push" | "otlp_attributes" | "gateway_log" | "connector";
  /**
   * When the interaction happened.
   */
  occurred_at: string;
  /**
   * When it was captured.
   */
  captured_at: string;
  /**
   * Agent canonical id. Null when not applicable.
   */
  agent_id?: CanonicalId | null;
  /**
   * Agent version canonical id. Null when not applicable.
   */
  agent_version_id?: CanonicalId | null;
  /**
   * Tool canonical id. Null when not applicable.
   */
  tool_id?: CanonicalId | null;
  /**
   * Service canonical id. Null when not applicable.
   */
  service_id?: CanonicalId | null;
  /**
   * MCP server canonical id. Null when not applicable.
   */
  mcp_server_id?: CanonicalId | null;
  /**
   * Model that served the interaction. Null when unknown.
   */
  model?: {
    /**
     * Provider token.
     */
    provider: string | null;
    /**
     * Model name as reported.
     */
    model_name: string | null;
    /**
     * Model version as reported.
     */
    model_version: string | null;
    /**
     * Model deployment canonical id.
     */
    deployment_id: CanonicalId | null;
  } | null;
  /**
   * Pseudonymous principal. Null when unknown.
   */
  principal_id?: string | null;
  /**
   * Capture policy that allowed the capture.
   */
  capture_policy_id: string;
  /**
   * Version of that capture policy.
   */
  capture_policy_version: number;
  /**
   * Version of the deterministic detector set.
   */
  detector_set_version: string;
  /**
   * `redacted`: detections replaced. `not_required`: nothing to replace. `redaction_failed`: nothing was stored (content_ref is null).
   */
  redaction_state: "redacted" | "not_required" | "redaction_failed";
  parts: ContentParts;
  /**
   * Encrypted content object. Null when nothing was stored.
   */
  content_ref: EncryptedObjectRef | null;
  /**
   * Per category counts of detector findings; category names and counts only.
   *
   * @maxItems 64
   */
  findings_summary?: {
    category: DetectedCategory;
    count: number;
    action: "replaced" | "kept";
  }[];
  sensitivity_categories?: SensitivityCategories;
  /**
   * Data assets the interaction touched.
   *
   * @maxItems 50
   */
  data_asset_ids?: CanonicalId[];
  /**
   * Retention class (slug).
   */
  retention_class?: string;
  /**
   * When the content expires (legal hold overrides).
   */
  expires_at: string;
  /**
   * Legal holds on this interaction.
   *
   * @maxItems 16
   *
   * Items: Identifier of a record inside a policy or configuration document (assignment, grant, budget, item).
   */
  legal_hold_ids?: string[];
}
/**
 * Reference to an AES-256-GCM encrypted object in content storage. The pointer is opaque and never fetched by schema validation; the wrapped data key lives in the blob header (PRP-102 decides). Only ciphertext is identified: no hash of plaintext.
 *
 * This interface was referenced by `InteractionRecord`'s JSON-Schema
 * via the `definition` "encrypted_object_ref".
 */
export interface EncryptedObjectRef {
  /**
   * Opaque storage pointer (blob path).
   */
  pointer: string;
  /**
   * Key Vault key identifier of the key-encryption key that wraps the data key (https://<vault>.vault.azure.net or usgovcloudapi.net /keys/<name>[/<32 hex version>]). A key identifier only; the vault suffix must match the document's cloud (tests/contracts/validators.py check_kek_uri_cloud).
   */
  kek_uri: string;
  /**
   * Content encryption algorithm.
   */
  algorithm: "aes_256_gcm";
  /**
   * SHA-256 of the ciphertext (lowercase hex), never of the plaintext.
   */
  ciphertext_sha256: string;
  /**
   * Size of the encrypted object in bytes.
   */
  byte_length: number;
}
