/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * OUTPUT-ONLY, SHOWN ONCE. Response to registering a producer or rotating its secret (PRP-41). secret is the only place in admin v1 where a credential value appears: it is generated server-side, returned once in this response, never stored (only secret_sha256 is) and can never be read back. It must not be logged, audited, cached or placed in a prompt; the audit record carries secret_sha256 only. No request schema may reference this schema.
 */
export interface ProducerSecretIssued {
  /**
   * Contract version of the document, major 1 with additive minor revisions (ADR-0004).
   */
  schema_version: string;
  producer_id: string;
  /**
   * Newly generated producer secret (URL-safe base64, at least 256 bits). Present the credential as Bearer <producer_id>.<secret>.
   */
  secret: string;
  secret_sha256: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required).
   */
  issued_at: string;
  /**
   * Always true: the secret cannot be retrieved again; rotate to get a new one.
   */
  shown_once: true;
}
