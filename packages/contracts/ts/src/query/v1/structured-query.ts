/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Semantic version of this document within major 1. Within v1 only additive, optional changes are allowed (ADR-0004).
 *
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "schema_version".
 */
export type SchemaVersion = string;
/**
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "catalog_entity".
 */
export type CatalogEntity =
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
  | "run_reference";
/**
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "filter".
 */
export type Filter =
  IdFilter | KeywordFilter | NumberFilter | MoneyFilter | TimeFilter | BooleanFilter;
/**
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "id_field".
 */
export type IdField =
  | "id"
  | "agent_id"
  | "agent_version_id"
  | "model_deployment_id"
  | "owner_id"
  | "domain_id"
  | "source_id"
  | "tool_id"
  | "service_id"
  | "policy_id"
  | "subject_id"
  | "principal_id";
/**
 * Canonical ID cloud:customer:source:type:id (PRP-01 clarification 7). Grammar owned by schemas/catalog/v1; duplicated here as a pattern.
 *
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "canonical_id".
 */
export type CanonicalId = string;
/**
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "keyword_field".
 */
export type KeywordField =
  | "cloud"
  | "environment"
  | "provider"
  | "model_name"
  | "model_version"
  | "lifecycle_status"
  | "outcome"
  | "status"
  | "kind"
  | "classification"
  | "span_kind"
  | "relation_status"
  | "observation_source"
  | "currency";
/**
 * Enumerated-style value: no whitespace, quotes, brackets, operators or control characters, so it cannot carry query text.
 *
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "keyword".
 */
export type Keyword = string;
/**
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "number_field".
 */
export type NumberField =
  | "confidence"
  | "duration_ms"
  | "input_tokens"
  | "output_tokens"
  | "cached_tokens"
  | "reasoning_tokens"
  | "total_tokens"
  | "retries"
  | "error_rate"
  | "latency_p50_ms"
  | "latency_p95_ms"
  | "request_count"
  | "score";
/**
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "money_field".
 */
export type MoneyField = "amount" | "baseline_amount" | "projected_amount";
/**
 * Money amount as a decimal string (no floats).
 *
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "decimal".
 */
export type Decimal = string;
/**
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "time_field".
 */
export type TimeField =
  | "event_time"
  | "ingestion_time"
  | "first_observed"
  | "last_observed"
  | "created_at"
  | "updated_at"
  | "completed_at";
/**
 * RFC 3339 timestamp in UTC (Z suffix required).
 *
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "timestamp".
 */
export type Timestamp = string;
/**
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "boolean_field".
 */
export type BooleanField = "advisory" | "locked" | "has_owner";
/**
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "any_field".
 */
export type AnyField = IdField | KeywordField | NumberField | MoneyField | TimeField | BooleanField;
/**
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "group_field".
 */
export type GroupField = IdField | KeywordField;
/**
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "alias".
 */
export type Alias = string;
/**
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "entity".
 */
export type Entity = CatalogEntity | ("telemetry_event" | "cost_record" | "evaluation_result");

/**
 * Request-side structured query used by REST, copilot tools and MCP (PRP.md section 3, NS-06). It carries structured allowlisted filters only, never executable query text: there is no free-text field, every field name is an allowlisted enum, every operator is typed per field kind, and string values are charset-restricted keywords or canonical IDs that the server binds as parameters (never concatenated into SQL/Cypher/KQL). Budgets (timeout_ms, limit, max_depth) are mandatory. Authorization comes only from the server-derived IdentityScope, which this schema never references: a domain_id or customer filter can only narrow results inside that scope. Rules JSON Schema cannot express: field applicability per entity is checked by tests/contracts/validators.py::check_structured_query_field_applicability; time_range.start < time_range.end by tests/contracts/validators.py::check_time_range_order; between bounds lo <= hi by tests/contracts/validators.py::check_between_order.
 */
export interface StructuredQuery {
  schema_version: SchemaVersion;
  /**
   * list and aggregate return rows; neighbors and impact_paths are bounded graph traversals from traversal.start_ids.
   */
  operation: "list" | "aggregate" | "neighbors" | "impact_paths";
  /**
   * Entity type returned (list, aggregate) or of the start nodes (neighbors, impact_paths).
   */
  entity: CatalogEntity | ("telemetry_event" | "cost_record" | "evaluation_result");
  /**
   * Conjunction (AND) of typed filters.
   *
   * @maxItems 32
   */
  filters?: Filter[];
  /**
   * Optional projection; allowlisted field names only.
   *
   * @maxItems 32
   */
  fields?: AnyField[];
  /**
   * @maxItems 3
   */
  sort?: SortKey[];
  time_range?: TimeRange;
  /**
   * @maxItems 3
   */
  group_by?: GroupField[];
  time_bucket?: "minute" | "five_minutes" | "hour" | "day" | "week";
  /**
   * @minItems 1
   * @maxItems 8
   */
  aggregations?: [Aggregation, ...Aggregation[]];
  traversal?: Traversal;
  budget: Budget;
  /**
   * Opaque, server-signed, base64url cursor. It encodes position only, never query text or filters, and is bound server-side to the caller's IdentityScope.
   */
  cursor?: string;
}
/**
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "id_filter".
 */
export interface IdFilter {
  field: IdField;
  op: "eq" | "ne" | "in" | "not_in";
  value?: CanonicalId;
  /**
   * @minItems 1
   * @maxItems 100
   */
  values?: [CanonicalId, ...CanonicalId[]];
}
/**
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "keyword_filter".
 */
export interface KeywordFilter {
  field: KeywordField;
  op: "eq" | "ne" | "in" | "not_in" | "prefix";
  value?: Keyword;
  /**
   * @minItems 1
   * @maxItems 100
   */
  values?: [Keyword, ...Keyword[]];
}
/**
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "number_filter".
 */
export interface NumberFilter {
  field: NumberField;
  op: "eq" | "ne" | "gt" | "gte" | "lt" | "lte" | "between";
  value?: number;
  /**
   * @minItems 2
   * @maxItems 2
   */
  values?: [number, number, ...number[]];
}
/**
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "money_filter".
 */
export interface MoneyFilter {
  field: MoneyField;
  op: "gt" | "gte" | "lt" | "lte" | "between";
  value?: Decimal;
  /**
   * @minItems 2
   * @maxItems 2
   */
  values?: [Decimal, Decimal, ...Decimal[]];
}
/**
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "time_filter".
 */
export interface TimeFilter {
  field: TimeField;
  op: "gt" | "gte" | "lt" | "lte" | "between";
  value?: Timestamp;
  /**
   * @minItems 2
   * @maxItems 2
   */
  values?: [Timestamp, Timestamp, ...Timestamp[]];
}
/**
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "boolean_filter".
 */
export interface BooleanFilter {
  field: BooleanField;
  op: "eq";
  value: boolean;
}
/**
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "sort_key".
 */
export interface SortKey {
  field: IdField | KeywordField | NumberField | MoneyField | TimeField | string;
  direction: "asc" | "desc";
}
/**
 * Half-open interval [start, end). start < end is checked by tests/contracts/validators.py::check_time_range_order.
 *
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "time_range".
 */
export interface TimeRange {
  start: Timestamp;
  end: Timestamp;
}
/**
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "aggregation".
 */
export interface Aggregation {
  op: "count" | "count_distinct" | "sum" | "avg" | "min" | "max" | "p50" | "p95" | "p99";
  field?: AnyField;
  as: Alias;
}
/**
 * Bounded traversal; depth and node/edge caps come from budget.
 *
 * This interface was referenced by `StructuredQuery`'s JSON-Schema
 * via the `definition` "traversal".
 */
export interface Traversal {
  /**
   * @minItems 1
   * @maxItems 50
   */
  start_ids: [CanonicalId, ...CanonicalId[]];
  /**
   * NS-02 relation names in lowercase snake_case.
   *
   * @minItems 1
   * @maxItems 9
   */
  relations: [
    (
      | "invokes"
      | "delegates_to"
      | "uses_model"
      | "reads"
      | "writes"
      | "grounded_by"
      | "owned_by"
      | "depends_on"
      | "supersedes"
    ),
    ...(
      | "invokes"
      | "delegates_to"
      | "uses_model"
      | "reads"
      | "writes"
      | "grounded_by"
      | "owned_by"
      | "depends_on"
      | "supersedes"
    )[],
  ];
  direction: "outgoing" | "incoming" | "both";
}
/**
 * Shared bounded-execution budget for every query, traversal, search, export and viewport expansion (PRP-01 clarification 15; NS-05, NS-06). timeout_ms, limit and max_depth are mandatory. The maxima here are contract ceilings; the server may clamp to lower policy values and reports the effective values and any truncation in Page. Not a standalone document, so it carries no schema_version.
 */
export interface Budget {
  /**
   * Wall-clock budget in integer milliseconds.
   */
  timeout_ms: number;
  /**
   * Maximum rows (or root items) per page.
   */
  limit: number;
  /**
   * Maximum traversal depth. 0 for non-graph queries.
   */
  max_depth: number;
  /**
   * Maximum graph nodes returned (viewport budget). Absent means the server policy default, never unbounded.
   */
  max_nodes?: number;
  /**
   * Maximum graph edges returned (viewport budget). Absent means the server policy default, never unbounded.
   */
  max_edges?: number;
}
