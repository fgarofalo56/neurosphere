/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Error response body for every NeuroSphere API, tool and MCP surface: an RFC 9457 problem details object profiled with the PRP.md section 3 taxonomy (code, retryable, correlation_id, optional reason, optional retry_after_seconds). Media type application/problem+json. The code -> status/retryable table is data in error-codes.json and is enforced here by allOf if/then. Rules JSON Schema cannot express are checked by Python validators in tests/contracts/test_error_taxonomy.py (PRP-01 item 7): test_error_table_matches_schema (error-codes.json and this allOf agree row for row) and, at runtime in PRP-05, the body status must equal the HTTP response status. detail and errors[].detail are human-readable and must never carry secrets, stack traces, query text or other tenants' data.
 */
export interface ProblemDetails {
  /**
   * Contract version of this document (semver within major 1).
   */
  schema_version: string;
  /**
   * RFC 9457 problem type, a URI reference. Use 'about:blank' or 'https://neurosphere.invalid/problems/<code>'. Never dereferenced by clients or tests.
   */
  type: string;
  /**
   * RFC 9457 short, human-readable summary of the problem type; does not vary between occurrences.
   */
  title: string;
  /**
   * RFC 9457 HTTP status code. Fixed per code by the allOf below; must equal the HTTP response status.
   */
  status: 401 | 403 | 409 | 422 | 429 | 502 | 503;
  /**
   * RFC 9457 occurrence-specific human-readable explanation. No secrets, stack traces or query text.
   */
  detail?: string;
  /**
   * RFC 9457 URI reference identifying this occurrence. Never dereferenced.
   */
  instance?: string;
  /**
   * NeuroSphere error taxonomy code (PRP.md section 3).
   */
  code:
    | "unauthorized"
    | "forbidden"
    | "capability_unavailable"
    | "stale_version"
    | "rate_limited"
    | "invalid_schema"
    | "dependency_transient";
  /**
   * Whether a client may retry the identical request automatically. Fixed per code.
   */
  retryable: boolean;
  /**
   * Correlation ID shared with logs, traces and audit records for this request.
   */
  correlation_id: string;
  /**
   * Machine-readable snake_case reason. Required for capability_unavailable (for example not_available_in_cloud, not_available_in_region, sku_unsupported, preview_only, outside_authorization_scope, disabled_by_policy); optional otherwise. Not free text.
   */
  reason?: string;
  /**
   * Seconds to wait before retrying; mirrors the Retry-After header. Required for rate_limited, optional for dependency_transient, forbidden when retryable is false.
   */
  retry_after_seconds?: number;
  /**
   * invalid_schema only: per-member validation failures (RFC 9457 section 3 'errors' extension shape).
   *
   * @minItems 1
   * @maxItems 100
   */
  errors?: [ValidationError, ...ValidationError[]];
}
/**
 * This interface was referenced by `ProblemDetails`'s JSON-Schema
 * via the `definition` "validation_error".
 */
export interface ValidationError {
  /**
   * RFC 6901 JSON Pointer into the request body.
   */
  pointer: string;
  /**
   * Human-readable failure; must not echo submitted values.
   */
  detail: string;
}
