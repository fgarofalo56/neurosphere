/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Opaque, server-signed, base64url cursor. It encodes position only, never query text or filters, and is bound server-side to the caller's IdentityScope.
 *
 * This interface was referenced by `Page`'s JSON-Schema
 * via the `definition` "cursor".
 */
export type Cursor = string;

/**
 * Shared cursor-based pagination block returned with every list response (PRP-01 clarification 15). The root schema is the response-side page; $defs/cursor is the opaque cursor a client echoes back on the next request. Cursors are server-issued and server-signed; a cursor that fails signature or scope binding is rejected as invalid_schema (behaviour in PRP-05, not expressible here). Not a standalone document, so it carries no schema_version. has_more=false with next_cursor non-null is rejected by the schema; returned <= limit is checked by tests/contracts/validators.py::check_page_counts.
 */
export interface Page {
  /**
   * Effective limit applied by the server after clamping the requested Budget.limit.
   */
  limit: number;
  /**
   * Items returned in this page.
   */
  returned: number;
  has_more: boolean;
  /**
   * Cursor for the next page, or null when has_more is false.
   */
  next_cursor: Cursor | null;
  /**
   * True when a budget other than limit stopped the result early (partial result, must be labelled in the UI).
   */
  truncated: boolean;
  /**
   * Which budget stopped the result. Required when truncated is true.
   */
  truncation_reason?: "max_nodes" | "max_edges" | "max_depth" | "timeout_ms";
}
