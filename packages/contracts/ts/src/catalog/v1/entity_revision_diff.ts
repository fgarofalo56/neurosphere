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
 * Computed difference between two retained revisions of one catalog entity (PRP-70; computed on read by PRP-76, never stored). Answers 'what changed between version N and M' including the declared-capability and tag diff of the original 5b story. changes is capped at 200 entries; truncated is true when more differences existed than were returned. before and after hold the compared values at that path (a scalar or a list, null when absent on that side; changed members of nested objects are reported as deeper paths, so a value is never an object) and are the entity's own field values, so the diff inherits the entity's visibility rules. Python validators: check_revision_version_order (from_version < to_version).
 */
export interface EntityRevisionDiff {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  entity_id: CanonicalId;
  /**
   * Catalog entity type; equals the type segment of the entity's canonical ID.
   */
  entity_type:
    | "person"
    | "agent"
    | "agent_version"
    | "model_deployment"
    | "grounding_source"
    | "tool"
    | "service"
    | "domain"
    | "owner"
    | "policy"
    | "recommendation"
    | "run_reference"
    | "grant"
    | "mcp_server";
  /**
   * Monotonic document version, incremented on every accepted write.
   */
  from_version: number;
  /**
   * Monotonic document version, incremented on every accepted write.
   */
  to_version: number;
  /**
   * @maxItems 200
   */
  changes: EntityRevisionChange[];
  capability_changes: EntityRevisionCapabilityChanges;
  tag_changes: EntityRevisionTagChanges;
  /**
   * True when the changes list was cut at its cap.
   */
  truncated: boolean;
}
/**
 * One differing field. path is an RFC 6901 JSON Pointer into the entity document (one to six lowercase snake_case segments, no array indexes).
 *
 * This interface was referenced by `EntityRevisionDiff`'s JSON-Schema
 * via the `definition` "change".
 */
export interface EntityRevisionChange {
  path: string;
  op: "added" | "removed" | "changed";
  /**
   * Value in from_version; null when op is added.
   */
  before?: string | number | boolean | unknown[] | null;
  /**
   * Value in to_version; null when op is removed.
   */
  after?: string | number | boolean | unknown[] | null;
}
/**
 * Declared capabilities added to and removed from the entity between the two versions.
 *
 * This interface was referenced by `EntityRevisionDiff`'s JSON-Schema
 * via the `definition` "capability_changes".
 */
export interface EntityRevisionCapabilityChanges {
  /**
   * @maxItems 64
   *
   * Items: Dot-namespaced capability token such as document.summarize (one to four segments). Open-ended: readers must tolerate unknown values. There is no closed taxonomy.
   */
  added: string[];
  /**
   * @maxItems 64
   *
   * Items: Dot-namespaced capability token such as document.summarize (one to four segments). Open-ended: readers must tolerate unknown values. There is no closed taxonomy.
   */
  removed: string[];
}
/**
 * Tags added to and removed from the entity between the two versions.
 *
 * This interface was referenced by `EntityRevisionDiff`'s JSON-Schema
 * via the `definition` "tag_changes".
 */
export interface EntityRevisionTagChanges {
  /**
   * @maxItems 64
   *
   * Items: Lowercase label token used for grouping and filtering catalog entities.
   */
  added: string[];
  /**
   * @maxItems 64
   *
   * Items: Lowercase label token used for grouping and filtering catalog entities.
   */
  removed: string[];
}
