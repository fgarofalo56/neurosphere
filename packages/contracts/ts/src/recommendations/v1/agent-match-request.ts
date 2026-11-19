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
 * Task-to-agent match request (PRP-70 item 3). task_text is tokenized for ranking only: it is never executed, never sent to an LLM for explanation and never stored (feedback keeps only a digest). The request carries no scope field: cloud, customer and domain scope come from the server-derived IdentityScope, so domain_id and customer_id are rejected as unknown keys. Nullable fields are optional and default to null.
 */
export interface AgentMatchRequest {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Natural-language task description, 3 to 2000 characters. Control characters other than tab and newline are rejected. Tokenized only, never executed or stored.
   */
  task_text: string;
  /**
   * Entity types to rank.
   *
   * @minItems 1
   * @maxItems 2
   */
  candidate_types?: ["agent" | "tool", ...("agent" | "tool")[]];
  /**
   * @maxItems 16
   *
   * Items: Dot-namespaced capability token such as document.summarize (one to four segments). Open-ended: readers must tolerate unknown values. There is no closed taxonomy.
   */
  required_capabilities?: string[];
  /**
   * @maxItems 16
   *
   * Items: Lowercase label token used for grouping and filtering catalog entities.
   */
  preferred_tags?: string[];
  /**
   * Canonical IDs of entities the task relates to; used as graph-proximity anchors.
   *
   * @maxItems 20
   */
  context_entity_ids?: CanonicalId[];
  /**
   * Restrict candidates to one environment; null means any.
   */
  environment?: ("production" | "staging" | "development" | "test" | "sandbox" | "unknown") | null;
  limit?: number;
  max_graph_depth?: number;
}
