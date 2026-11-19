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
 * Notice that the live map topology of a domain changed (PRP-70 item 4). A fragment schema without schema_version, like actions/v1/target-ref. It names what changed so a client can refetch; it carries no node or edge bodies. When truncated is true the entity_ids list is partial and the client must refetch.
 */
export interface MapTopologyChange {
  /**
   * Owning domain; authorization scope anchor. Canonical ID (canonical_id.schema.json) whose type segment is 'domain'.
   */
  domain_id: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  changed_at: string;
  /**
   * @minItems 1
   */
  change_kinds: [
    "node_added" | "node_removed" | "node_updated" | "edge_added" | "edge_removed" | "edge_updated",
    ...(
      | "node_added"
      | "node_removed"
      | "node_updated"
      | "edge_added"
      | "edge_removed"
      | "edge_updated"
    )[],
  ];
  /**
   * Canonical ids of the entities touched; at most 50.
   *
   * @maxItems 50
   */
  entity_ids: CanonicalId[];
  refetch: boolean;
  truncated: boolean;
}
