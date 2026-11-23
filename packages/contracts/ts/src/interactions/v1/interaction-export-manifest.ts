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
 * Manifest of one interaction content export (PRP-99). Metadata only: ids, counts, the purpose and an encrypted bundle reference; no content. Written by PRP-104.
 */
export interface InteractionExportManifest {
  /**
   * Contract version of this document, major 1 with additive minor revisions.
   */
  schema_version: string;
  /**
   * Export identifier (lowercase UUID).
   */
  export_id: string;
  /**
   * Sovereign cloud boundary.
   */
  cloud: "commercial" | "government";
  /**
   * Customer segment.
   */
  customer_id: string;
  /**
   * Domains the export draws from.
   *
   * @minItems 1
   * @maxItems 64
   *
   * Items: Owning domain; authorization scope anchor. Canonical ID (canonical_id.schema.json) whose type segment is 'domain'.
   */
  domain_ids: [string, ...string[]];
  /**
   * Requesting principal (pseudonym).
   */
  requested_by: string;
  /**
   * When requested.
   */
  requested_at: string;
  purpose: InteractionAccessPurpose;
  /**
   * Selection filters.
   */
  filters: {
    /**
     * Start of the window.
     */
    from: string;
    /**
     * End of the window.
     */
    to: string;
    /**
     * @maxItems 64
     */
    agent_ids: CanonicalId[];
    /**
     * @maxItems 32
     */
    detected_categories: DetectedCategory[];
  };
  /**
   * Interactions in the bundle.
   */
  interaction_count: number;
  /**
   * Interactions in the bundle.
   *
   * @maxItems 1000
   */
  interaction_ids: string[];
  /**
   * Interactions excluded (no permission, expired or held).
   */
  excluded_count: number;
  /**
   * Whether content under legal hold is included.
   */
  includes_held_content: boolean;
  bundle: EncryptedObjectRef;
  /**
   * Audit record of the export.
   */
  audit_id: string;
  /**
   * When the bundle expires.
   */
  expires_at: string;
}
/**
 * Why the export was requested.
 */
export interface InteractionAccessPurpose {
  /**
   * Purpose of the access; open-ended: readers must tolerate unknown values.
   */
  purpose_code:
    | "incident_investigation"
    | "policy_violation_review"
    | "legal_hold_review"
    | "data_subject_request"
    | "security_review"
    | "quality_review";
  /**
   * Case record id (admin record_id). Null when none.
   */
  case_ref: string | null;
}
/**
 * Encrypted export bundle.
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
