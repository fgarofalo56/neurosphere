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
 * Transient opt-in content push (PRP-99): the prompt, response and tool text of one observed event, sent to the ingest edge only when a capture policy allows it. It is never stored, published, logged or returned; the edge redacts it (RedactedContent) and keeps only metadata on the event (payload_ref). The pair (source_id, event_id) joins it to its TelemetryEvent. Nothing but this schema and RedactedContent carries text; no other schema references it. Rule JSON Schema cannot express, enforced by the Python validator check_content_envelope_parts in tests/contracts/validators.py: at most one part per kind.
 */
export interface ContentEnvelope {
  /**
   * Contract version of this document, major 1 with additive minor revisions.
   */
  schema_version: string;
  /**
   * Azure cloud boundary the content belongs to. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Producer that emitted the event.
   */
  source_id: string;
  /**
   * Source-assigned event identifier; with source_id it joins this envelope to its TelemetryEvent.
   */
  event_id: string;
  /**
   * W3C/OpenTelemetry trace ID, 32 lowercase hex characters.
   */
  trace_id: string;
  /**
   * Span ID, 16 lowercase hex characters. Null when not reported.
   */
  span_id?: string | null;
  /**
   * When the observed event happened at the source (RFC 3339 UTC).
   */
  occurred_at: string;
  /**
   * Content parts, one per kind, 1 to 5.
   *
   * @minItems 1
   * @maxItems 5
   */
  parts: [ContentPart, ...ContentPart[]];
}
/**
 * One part of the interaction content, exactly as the producer observed it (not yet redacted).
 *
 * This interface was referenced by `ContentEnvelope`'s JSON-Schema
 * via the `definition` "content_part".
 */
export interface ContentPart {
  part: ContentPartKind;
  /**
   * Part text, 1 to 32768 characters, no control characters except tab, CR and LF.
   */
  text: string;
  /**
   * True when the producer cut the text before sending.
   */
  truncated?: boolean;
}
