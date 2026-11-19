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
 * Free-form lowercase labels; at most 32, no duplicates.
 *
 * @maxItems 32
 *
 * Items: Lowercase label token used for grouping and filtering catalog entities.
 */
export type Tags = string[];
/**
 * Declared capabilities; at most 64, no duplicates.
 *
 * @maxItems 64
 *
 * Items: Dot-namespaced capability token such as document.summarize (one to four segments). Open-ended: readers must tolerate unknown values. There is no closed taxonomy.
 */
export type Capabilities = string[];
/**
 * Free-form lowercase labels; at most 32, no duplicates.
 *
 * @maxItems 32
 *
 * Items: Lowercase label token used for grouping and filtering catalog entities.
 */
export type Tags1 = string[];
/**
 * Declared capabilities; at most 64, no duplicates.
 *
 * @maxItems 64
 *
 * Items: Dot-namespaced capability token such as document.summarize (one to four segments). Open-ended: readers must tolerate unknown values. There is no closed taxonomy.
 */
export type Capabilities1 = string[];
/**
 * Free-form lowercase labels; at most 32, no duplicates.
 *
 * @maxItems 32
 *
 * Items: Lowercase label token used for grouping and filtering catalog entities.
 */
export type Tags2 = string[];
/**
 * Free-form lowercase labels; at most 32, no duplicates.
 *
 * @maxItems 32
 *
 * Items: Lowercase label token used for grouping and filtering catalog entities.
 */
export type Tags3 = string[];
/**
 * Sensitivity categories of a data asset; empty when none are declared or not yet assessed.
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
 * Free-form lowercase labels; at most 32, no duplicates.
 *
 * @maxItems 32
 *
 * Items: Lowercase label token used for grouping and filtering catalog entities.
 */
export type Tags4 = string[];
/**
 * Declared capabilities; at most 64, no duplicates.
 *
 * @maxItems 64
 *
 * Items: Dot-namespaced capability token such as document.summarize (one to four segments). Open-ended: readers must tolerate unknown values. There is no closed taxonomy.
 */
export type Capabilities2 = string[];
/**
 * Free-form lowercase labels; at most 32, no duplicates.
 *
 * @maxItems 32
 *
 * Items: Lowercase label token used for grouping and filtering catalog entities.
 */
export type Tags5 = string[];
/**
 * Free-form lowercase labels; at most 32, no duplicates.
 *
 * @maxItems 32
 *
 * Items: Lowercase label token used for grouping and filtering catalog entities.
 */
export type Tags6 = string[];

/**
 * One immutable, retained revision of a catalog entity (PRP-70; the revision store and writer are PRP-76). revision_id is '<entity canonical id>@<entity_version>'; JSON Schema checks only that it is a canonical id followed by '@' and a positive integer, and core must also check that the id and version equal entity_id and entity_version (documented for PRP-76). body holds the full entity document as it was at that version; JSON Schema pins it to the schema named by entity_type (allOf below, the AdminConfigDocument precedent) and the generated Pydantic model cannot express that pin (ADR-0004 shape projection), so core validates body again against the entity's own model. body_sha256 is a 'sha256:' digest of body; the canonical serialization the digest covers is defined by the revision writer (PRP-76), not by this contract, which fixes the shape only. Nullable members are optional and default to null, as on the catalog entities. Python validators: check_revision_version_order (previous_version < entity_version when previous_version is not null).
 */
export interface EntityRevision {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * '<entity canonical id>@<entity_version>', unique per entity and version.
   */
  revision_id: string;
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
   * The entity's own version recorded by this revision.
   */
  entity_version: number;
  /**
   * Entity version this revision replaced; null for the first revision or when the history starts here.
   */
  previous_version?: number | null;
  /**
   * Sovereign cloud boundary. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Customer segment of the canonical ID grammar.
   */
  customer_id: string;
  /**
   * Owning domain; authorization scope anchor. Canonical ID (canonical_id.schema.json) whose type segment is 'domain'.
   */
  domain_id: string;
  operation: "create" | "update" | "deprecate" | "recertify" | "retire" | "import" | "projection";
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  recorded_at: string;
  /**
   * Pseudonymous person id that made the change; null for workers and connectors.
   */
  recorded_by?: string | null;
  /**
   * Top-level property names of the entity that differ from the previous revision.
   *
   * @maxItems 64
   */
  changed_fields: string[];
  change_reason?: string | null;
  /**
   * Audit record that logged the change (lowercase UUID); null when none exists, for example a projection.
   */
  audit_id?: string | null;
  correlation_id?: string | null;
  /**
   * Digest of body; shape only, the serialization it covers is defined by the revision writer (PRP-76).
   */
  body_sha256: string;
  /**
   * The full entity document at entity_version; allOf below pins which entity schema it must satisfy. Never a credential value.
   */
  body:
    | Person
    | Agent
    | AgentVersion
    | ModelDeployment
    | GroundingSource
    | Tool
    | Service
    | Domain
    | Owner
    | Policy
    | RecommendationReference
    | RunReference
    | Grant
    | McpServer;
}
/**
 * Person as a pseudonymous principal only. There is deliberately no email, name, UPN, display_name, free-text or attributes field; re-identification is a policy-store concern, not a contract field. The id segment of the canonical ID is the pseudonym. Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at), validate_person_id_is_pseudonym (id segment equals principal_pseudonym).
 */
export interface Person {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Canonical ID whose id segment is the principal pseudonym (psn_...).
   */
  id: string;
  entity_type: "person";
  /**
   * Monotonic document version, incremented on every accepted write.
   */
  version: number;
  /**
   * Opaque optimistic-concurrency token. A mismatch on write returns the stale_version error.
   */
  etag: string;
  /**
   * Entity lifecycle state.
   */
  lifecycle_status: "draft" | "active" | "deprecated" | "retired";
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  created_at: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  updated_at: string;
  /**
   * Sovereign cloud boundary. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Customer segment of the canonical ID grammar.
   */
  customer_id: string;
  /**
   * Stable pseudonym produced by the pseudonymization service.
   */
  principal_pseudonym: string;
  /**
   * Pseudonymization scheme and key version, for rotation.
   */
  pseudonym_scheme: string;
  principal_kind?: "human" | "workload" | "unknown";
  /**
   * Home domain when known; people may act across domains.
   */
  domain_id?: string | null;
}
/**
 * AI agent as a logical, versioned catalog entity; concrete releases are AgentVersion. Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at).
 */
export interface Agent {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Stable canonical ID of this entity. Canonical ID (canonical_id.schema.json) whose type segment is 'agent'.
   */
  id: string;
  entity_type: "agent";
  /**
   * Monotonic document version, incremented on every accepted write.
   */
  version: number;
  /**
   * Opaque optimistic-concurrency token. A mismatch on write returns the stale_version error.
   */
  etag: string;
  /**
   * Entity lifecycle state.
   */
  lifecycle_status: "draft" | "active" | "deprecated" | "retired";
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  created_at: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  updated_at: string;
  /**
   * Sovereign cloud boundary. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Customer segment of the canonical ID grammar.
   */
  customer_id: string;
  /**
   * Owning domain; authorization scope anchor. Canonical ID (canonical_id.schema.json) whose type segment is 'domain'.
   */
  domain_id: string;
  /**
   * Data classification label; unknown when not yet classified.
   */
  classification?: "public" | "internal" | "confidential" | "restricted" | "unknown";
  /**
   * Azure region holding the authoritative copy; null when unknown.
   */
  residency_region?: string | null;
  attributes?: Attributes;
  /**
   * Human-readable label for a non-person entity. Never a person's name.
   */
  display_name: string;
  description?: string | null;
  agent_kind?: "assistant" | "workflow" | "sub_agent" | "autonomous" | "unknown";
  /**
   * Lowercase identifier token (source IDs, platforms, providers, kinds).
   */
  platform: string;
  /**
   * Lowercase identifier token (source IDs, platforms, providers, kinds).
   */
  source_id: string;
  /**
   * Source-native agent identifier; resolution to this ID is recorded by alias documents.
   */
  external_agent_id?: string | null;
  current_version_id?: string | null;
  tags?: Tags;
  capabilities?: Capabilities;
  /**
   * Deployment environment; the same vocabulary as TelemetryEvent.environment.
   */
  environment?: "production" | "staging" | "development" | "test" | "sandbox" | "unknown";
}
/**
 * Extension point: scalar values only (string, number, boolean, null); keys are lowercase snake_case. Nested objects and arrays are rejected.
 */
export interface Attributes {
  /**
   * This interface was referenced by `Attributes`'s JSON-Schema definition
   * via the `patternProperty` "^[a-z][a-z0-9_]{0,63}$".
   */
  [k: string]: string | number | boolean | null | undefined;
}
/**
 * Immutable release of an Agent (instructions, tools and model bindings at a point in time). Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at).
 */
export interface AgentVersion {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Stable canonical ID of this entity. Canonical ID (canonical_id.schema.json) whose type segment is 'agent_version'.
   */
  id: string;
  entity_type: "agent_version";
  /**
   * Monotonic document version, incremented on every accepted write.
   */
  version: number;
  /**
   * Opaque optimistic-concurrency token. A mismatch on write returns the stale_version error.
   */
  etag: string;
  /**
   * Entity lifecycle state.
   */
  lifecycle_status: "draft" | "active" | "deprecated" | "retired";
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  created_at: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  updated_at: string;
  /**
   * Sovereign cloud boundary. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Customer segment of the canonical ID grammar.
   */
  customer_id: string;
  /**
   * Owning domain; authorization scope anchor. Canonical ID (canonical_id.schema.json) whose type segment is 'domain'.
   */
  domain_id: string;
  /**
   * Data classification label; unknown when not yet classified.
   */
  classification?: "public" | "internal" | "confidential" | "restricted" | "unknown";
  /**
   * Azure region holding the authoritative copy; null when unknown.
   */
  residency_region?: string | null;
  attributes?: Attributes;
  /**
   * Parent Agent. Canonical ID (canonical_id.schema.json) whose type segment is 'agent'.
   */
  agent_id: string;
  version_label: string;
  released_at?: string | null;
  /**
   * Hash of the version's declarative configuration.
   */
  config_hash?: string | null;
  tags?: Tags1;
  capabilities?: Capabilities1;
  /**
   * Declared Semantic Version of this release; null when not declared (version_label stays the free-form label).
   */
  semver?: string | null;
}
/**
 * Deployed model endpoint with version, modality, context, tool capability and price reference. Unknown capabilities are null, never 0. Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at).
 */
export interface ModelDeployment {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Stable canonical ID of this entity. Canonical ID (canonical_id.schema.json) whose type segment is 'model_deployment'.
   */
  id: string;
  entity_type: "model_deployment";
  /**
   * Monotonic document version, incremented on every accepted write.
   */
  version: number;
  /**
   * Opaque optimistic-concurrency token. A mismatch on write returns the stale_version error.
   */
  etag: string;
  /**
   * Entity lifecycle state.
   */
  lifecycle_status: "draft" | "active" | "deprecated" | "retired";
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  created_at: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  updated_at: string;
  /**
   * Sovereign cloud boundary. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Customer segment of the canonical ID grammar.
   */
  customer_id: string;
  /**
   * Owning domain; authorization scope anchor. Canonical ID (canonical_id.schema.json) whose type segment is 'domain'.
   */
  domain_id: string;
  /**
   * Data classification label; unknown when not yet classified.
   */
  classification?: "public" | "internal" | "confidential" | "restricted" | "unknown";
  /**
   * Azure region holding the authoritative copy; null when unknown.
   */
  residency_region?: string | null;
  attributes?: Attributes;
  /**
   * Lowercase identifier token (source IDs, platforms, providers, kinds).
   */
  provider: string;
  model_name: string;
  model_version?: string | null;
  deployment_name: string;
  modalities?: ("text" | "image" | "audio" | "video" | "embedding" | "unknown")[];
  /**
   * Maximum context window; null when unknown.
   */
  context_window_tokens?: number | null;
  /**
   * Maximum output tokens; null when unknown.
   */
  max_output_tokens?: number | null;
  /**
   * null when unknown.
   */
  supports_tool_calling?: boolean | null;
  region?: string | null;
  sku?: string | null;
  /**
   * Price sheet reference used for estimates; null when unpriced.
   */
  price_reference?: {
    price_version: string;
    /**
     * RFC 3339 full-date.
     */
    price_effective_date: string;
  } | null;
  tags?: Tags2;
  /**
   * Deployment environment; the same vocabulary as TelemetryEvent.environment.
   */
  environment?: "production" | "staging" | "development" | "test" | "sandbox" | "unknown";
}
/**
 * GroundingSource/DataAsset: a data asset read, written or used for grounding (index, store, table, file share, knowledge base). One schema covers both names. Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at).
 */
export interface GroundingSource {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Stable canonical ID of this entity. Canonical ID (canonical_id.schema.json) whose type segment is 'grounding_source'.
   */
  id: string;
  entity_type: "grounding_source";
  /**
   * Monotonic document version, incremented on every accepted write.
   */
  version: number;
  /**
   * Opaque optimistic-concurrency token. A mismatch on write returns the stale_version error.
   */
  etag: string;
  /**
   * Entity lifecycle state.
   */
  lifecycle_status: "draft" | "active" | "deprecated" | "retired";
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  created_at: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  updated_at: string;
  /**
   * Sovereign cloud boundary. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Customer segment of the canonical ID grammar.
   */
  customer_id: string;
  /**
   * Owning domain; authorization scope anchor. Canonical ID (canonical_id.schema.json) whose type segment is 'domain'.
   */
  domain_id: string;
  /**
   * Data classification label; unknown when not yet classified.
   */
  classification?: "public" | "internal" | "confidential" | "restricted" | "unknown";
  /**
   * Azure region holding the authoritative copy; null when unknown.
   */
  residency_region?: string | null;
  attributes?: Attributes;
  /**
   * Human-readable label for a non-person entity. Never a person's name.
   */
  display_name: string;
  asset_kind?:
    | "search_index"
    | "vector_store"
    | "database"
    | "table"
    | "file_store"
    | "knowledge_base"
    | "api"
    | "other"
    | "unknown";
  /**
   * Lowercase identifier token (source IDs, platforms, providers, kinds).
   */
  source_id: string;
  /**
   * Provider resource reference; a pointer, never fetched.
   */
  resource_ref?: string | null;
  /**
   * null when not assessed.
   */
  contains_personal_data?: boolean | null;
  tags?: Tags3;
  /**
   * Deployment environment; the same vocabulary as TelemetryEvent.environment.
   */
  environment?: "production" | "staging" | "development" | "test" | "sandbox" | "unknown";
  sensitivity_categories?: SensitivityCategories;
  /**
   * Coarse geography of the authoritative copy; null when not declared (consumers derive it from residency_region).
   */
  residency_geography?:
    | (
        | "eu_eea"
        | "uk"
        | "switzerland"
        | "united_states"
        | "canada"
        | "asia_pacific"
        | "latin_america"
        | "middle_east_africa"
        | "other"
      )
    | null;
}
/**
 * Callable tool exposed to agents (function, API, MCP tool, search, code interpreter). Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at).
 */
export interface Tool {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Stable canonical ID of this entity. Canonical ID (canonical_id.schema.json) whose type segment is 'tool'.
   */
  id: string;
  entity_type: "tool";
  /**
   * Monotonic document version, incremented on every accepted write.
   */
  version: number;
  /**
   * Opaque optimistic-concurrency token. A mismatch on write returns the stale_version error.
   */
  etag: string;
  /**
   * Entity lifecycle state.
   */
  lifecycle_status: "draft" | "active" | "deprecated" | "retired";
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  created_at: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  updated_at: string;
  /**
   * Sovereign cloud boundary. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Customer segment of the canonical ID grammar.
   */
  customer_id: string;
  /**
   * Owning domain; authorization scope anchor. Canonical ID (canonical_id.schema.json) whose type segment is 'domain'.
   */
  domain_id: string;
  /**
   * Data classification label; unknown when not yet classified.
   */
  classification?: "public" | "internal" | "confidential" | "restricted" | "unknown";
  /**
   * Azure region holding the authoritative copy; null when unknown.
   */
  residency_region?: string | null;
  attributes?: Attributes;
  /**
   * Human-readable label for a non-person entity. Never a person's name.
   */
  display_name: string;
  tool_kind?: "function" | "api" | "mcp_tool" | "search" | "code_interpreter" | "other" | "unknown";
  side_effects?: "read_only" | "writes" | "unknown";
  /**
   * Lowercase identifier token (source IDs, platforms, providers, kinds).
   */
  source_id: string;
  mcp_server_ref?: string | null;
  tags?: Tags4;
  capabilities?: Capabilities2;
  /**
   * Deployment environment; the same vocabulary as TelemetryEvent.environment.
   */
  environment?: "production" | "staging" | "development" | "test" | "sandbox" | "unknown";
}
/**
 * Service an agent or tool depends on (Azure service, SaaS, internal API, gateway). Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at).
 */
export interface Service {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Stable canonical ID of this entity. Canonical ID (canonical_id.schema.json) whose type segment is 'service'.
   */
  id: string;
  entity_type: "service";
  /**
   * Monotonic document version, incremented on every accepted write.
   */
  version: number;
  /**
   * Opaque optimistic-concurrency token. A mismatch on write returns the stale_version error.
   */
  etag: string;
  /**
   * Entity lifecycle state.
   */
  lifecycle_status: "draft" | "active" | "deprecated" | "retired";
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  created_at: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  updated_at: string;
  /**
   * Sovereign cloud boundary. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Customer segment of the canonical ID grammar.
   */
  customer_id: string;
  /**
   * Owning domain; authorization scope anchor. Canonical ID (canonical_id.schema.json) whose type segment is 'domain'.
   */
  domain_id: string;
  /**
   * Data classification label; unknown when not yet classified.
   */
  classification?: "public" | "internal" | "confidential" | "restricted" | "unknown";
  /**
   * Azure region holding the authoritative copy; null when unknown.
   */
  residency_region?: string | null;
  attributes?: Attributes;
  /**
   * Human-readable label for a non-person entity. Never a person's name.
   */
  display_name: string;
  service_kind?: "azure_service" | "saas" | "internal_api" | "gateway" | "other" | "unknown";
  /**
   * Lowercase identifier token (source IDs, platforms, providers, kinds).
   */
  source_id: string;
  azure_resource_type?: string | null;
  tags?: Tags5;
  /**
   * Deployment environment; the same vocabulary as TelemetryEvent.environment.
   */
  environment?: "production" | "staging" | "development" | "test" | "sandbox" | "unknown";
}
/**
 * Governance domain: the authorization and federation scope unit. Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at).
 */
export interface Domain {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Stable canonical ID of this entity. Canonical ID (canonical_id.schema.json) whose type segment is 'domain'.
   */
  id: string;
  entity_type: "domain";
  /**
   * Monotonic document version, incremented on every accepted write.
   */
  version: number;
  /**
   * Opaque optimistic-concurrency token. A mismatch on write returns the stale_version error.
   */
  etag: string;
  /**
   * Entity lifecycle state.
   */
  lifecycle_status: "draft" | "active" | "deprecated" | "retired";
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  created_at: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  updated_at: string;
  /**
   * Sovereign cloud boundary. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Customer segment of the canonical ID grammar.
   */
  customer_id: string;
  /**
   * Data classification label; unknown when not yet classified.
   */
  classification?: "public" | "internal" | "confidential" | "restricted" | "unknown";
  /**
   * Azure region holding the authoritative copy; null when unknown.
   */
  residency_region?: string | null;
  attributes?: Attributes;
  /**
   * Human-readable label for a non-person entity. Never a person's name.
   */
  display_name: string;
  parent_domain_id?: string | null;
}
/**
 * Accountable owner (team, group, service principal or pseudonymous person) targeted by OWNED_BY. A person-kind owner carries no display_name; it points at a Person. Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at).
 */
export interface Owner {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Stable canonical ID of this entity. Canonical ID (canonical_id.schema.json) whose type segment is 'owner'.
   */
  id: string;
  entity_type: "owner";
  /**
   * Monotonic document version, incremented on every accepted write.
   */
  version: number;
  /**
   * Opaque optimistic-concurrency token. A mismatch on write returns the stale_version error.
   */
  etag: string;
  /**
   * Entity lifecycle state.
   */
  lifecycle_status: "draft" | "active" | "deprecated" | "retired";
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  created_at: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  updated_at: string;
  /**
   * Sovereign cloud boundary. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Customer segment of the canonical ID grammar.
   */
  customer_id: string;
  /**
   * Owning domain; authorization scope anchor. Canonical ID (canonical_id.schema.json) whose type segment is 'domain'.
   */
  domain_id: string;
  /**
   * Data classification label; unknown when not yet classified.
   */
  classification?: "public" | "internal" | "confidential" | "restricted" | "unknown";
  /**
   * Azure region holding the authoritative copy; null when unknown.
   */
  residency_region?: string | null;
  attributes?: Attributes;
  owner_kind: "person" | "group" | "team" | "service_principal";
  display_name?: string | null;
  principal_id?: string | null;
  recertified_at?: string | null;
  recertify_by?: string | null;
}
/**
 * Governance policy applied to catalog entities (access, data handling, model usage, cost). Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at).
 */
export interface Policy {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Stable canonical ID of this entity. Canonical ID (canonical_id.schema.json) whose type segment is 'policy'.
   */
  id: string;
  entity_type: "policy";
  /**
   * Monotonic document version, incremented on every accepted write.
   */
  version: number;
  /**
   * Opaque optimistic-concurrency token. A mismatch on write returns the stale_version error.
   */
  etag: string;
  /**
   * Entity lifecycle state.
   */
  lifecycle_status: "draft" | "active" | "deprecated" | "retired";
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  created_at: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  updated_at: string;
  /**
   * Sovereign cloud boundary. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Customer segment of the canonical ID grammar.
   */
  customer_id: string;
  /**
   * Owning domain; authorization scope anchor. Canonical ID (canonical_id.schema.json) whose type segment is 'domain'.
   */
  domain_id: string;
  /**
   * Data classification label; unknown when not yet classified.
   */
  classification?: "public" | "internal" | "confidential" | "restricted" | "unknown";
  /**
   * Azure region holding the authoritative copy; null when unknown.
   */
  residency_region?: string | null;
  attributes?: Attributes;
  /**
   * Human-readable label for a non-person entity. Never a person's name.
   */
  display_name: string;
  policy_kind:
    "access" | "data_handling" | "model_usage" | "cost" | "retention" | "approval" | "other";
  policy_version: string;
  enforcement: "enforced" | "advisory" | "disabled";
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  effective_from: string;
  effective_to?: string | null;
  document_ref?: string | null;
}
/**
 * Recommendation in reference form for the catalog graph. The full document is the recommendations/v1 contract; this node only points at it and its subjects. Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at).
 */
export interface RecommendationReference {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Stable canonical ID of this entity. Canonical ID (canonical_id.schema.json) whose type segment is 'recommendation'.
   */
  id: string;
  entity_type: "recommendation";
  /**
   * Monotonic document version, incremented on every accepted write.
   */
  version: number;
  /**
   * Opaque optimistic-concurrency token. A mismatch on write returns the stale_version error.
   */
  etag: string;
  /**
   * Entity lifecycle state.
   */
  lifecycle_status: "draft" | "active" | "deprecated" | "retired";
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  created_at: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  updated_at: string;
  /**
   * Sovereign cloud boundary. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Customer segment of the canonical ID grammar.
   */
  customer_id: string;
  /**
   * Owning domain; authorization scope anchor. Canonical ID (canonical_id.schema.json) whose type segment is 'domain'.
   */
  domain_id: string;
  /**
   * Data classification label; unknown when not yet classified.
   */
  classification?: "public" | "internal" | "confidential" | "restricted" | "unknown";
  /**
   * Azure region holding the authoritative copy; null when unknown.
   */
  residency_region?: string | null;
  attributes?: Attributes;
  /**
   * Lowercase identifier token (source IDs, platforms, providers, kinds).
   */
  recommendation_kind: string;
  /**
   * Identifier of the full recommendations/v1 document.
   */
  recommendation_document_id: string;
  /**
   * @minItems 1
   * @maxItems 100
   */
  subject_ids: [string, ...string[]];
}
/**
 * Pointer to a run held in the telemetry store. Runs and spans are referenced, never replicated into the graph; no prompt or response body appears here. Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at).
 */
export interface RunReference {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Stable canonical ID of this entity. Canonical ID (canonical_id.schema.json) whose type segment is 'run_reference'.
   */
  id: string;
  entity_type: "run_reference";
  /**
   * Monotonic document version, incremented on every accepted write.
   */
  version: number;
  /**
   * Opaque optimistic-concurrency token. A mismatch on write returns the stale_version error.
   */
  etag: string;
  /**
   * Entity lifecycle state.
   */
  lifecycle_status: "draft" | "active" | "deprecated" | "retired";
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  created_at: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  updated_at: string;
  /**
   * Sovereign cloud boundary. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Customer segment of the canonical ID grammar.
   */
  customer_id: string;
  /**
   * Owning domain; authorization scope anchor. Canonical ID (canonical_id.schema.json) whose type segment is 'domain'.
   */
  domain_id: string;
  /**
   * Data classification label; unknown when not yet classified.
   */
  classification?: "public" | "internal" | "confidential" | "restricted" | "unknown";
  /**
   * Azure region holding the authoritative copy; null when unknown.
   */
  residency_region?: string | null;
  attributes?: Attributes;
  /**
   * Agent that executed the run. Canonical ID (canonical_id.schema.json) whose type segment is 'agent'.
   */
  agent_id: string;
  agent_version_id?: string | null;
  source_run_id: string;
  /**
   * W3C trace ID.
   */
  trace_id?: string | null;
  request_id?: string | null;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  started_at: string;
  ended_at?: string | null;
  outcome?: "success" | "error" | "cancelled" | "timeout" | "unknown";
  /**
   * Number of spans; null when unknown.
   */
  span_count?: number | null;
}
/**
 * Access grant of one Entra principal (user, application, agent or Entra group) to one target (a model API, a model deployment or an MCP server) with optional usage limits and a cost center. It is the unit a gateway enforces (PRP-34); this document is desired state only and records no enforcement. Cross-field rules enforced in this schema: target.ref carries the type segment of target.kind (model_api is a 'service' entity, model_deployment a 'model_deployment', mcp_server an 'mcp_server'); MCP grants are call-limited only (tokens_per_minute, token_quota, quota_period and requests_per_minute must be null) and model grants carry no mcp_calls_per_minute; token_quota and quota_period are set together; a user principal carries no display label (person names are never stored). The generated Pydantic model does not carry these conditionals (ADR-0004); JSON Schema is the source of truth. Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at), validate_grant_window (valid_from < valid_until when both are set).
 */
export interface Grant {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Stable canonical ID of this entity. Canonical ID (canonical_id.schema.json) whose type segment is 'grant'. The owning domain is domain_id, as for every catalog entity.
   */
  id: string;
  entity_type: "grant";
  /**
   * Monotonic document version, incremented on every accepted write.
   */
  version: number;
  /**
   * Opaque optimistic-concurrency token. A mismatch on write returns the stale_version error.
   */
  etag: string;
  /**
   * Entity lifecycle state.
   */
  lifecycle_status: "draft" | "active" | "deprecated" | "retired";
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  created_at: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  updated_at: string;
  /**
   * Sovereign cloud boundary. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Customer segment of the canonical ID grammar.
   */
  customer_id: string;
  /**
   * Owning domain; authorization scope anchor. Canonical ID (canonical_id.schema.json) whose type segment is 'domain'.
   */
  domain_id: string;
  /**
   * Data classification label; unknown when not yet classified.
   */
  classification?: "public" | "internal" | "confidential" | "restricted" | "unknown";
  /**
   * Azure region holding the authoritative copy; null when unknown.
   */
  residency_region?: string | null;
  attributes?: Attributes;
  /**
   * The Entra principal the grant applies to. Gateways match object_id against the token 'oid' claim (user, application, agent) or the 'groups' claim (entra_group).
   */
  principal: {
    kind: "user" | "application" | "agent" | "entra_group";
    /**
     * Entra object ID (GUID) of the principal, lowercase hyphenated form (claims are compared as exact strings). A pattern rather than format uuid keeps the generated models wire-exact strings.
     */
    object_id: string;
    /**
     * Label of an application, agent or group. Must be null for a user principal: person names are never stored in the catalog.
     */
    display?: string | null;
  };
  /**
   * What the principal may call. ref is the canonical ID of the target catalog entity; its type segment follows kind (model_api -> service, model_deployment -> model_deployment, mcp_server -> mcp_server).
   */
  target: {
    kind: "model_api" | "model_deployment" | "mcp_server";
    /**
     * Target entity. Canonical ID (canonical_id.schema.json) whose type segment is 'service' or 'model_deployment' or 'mcp_server'.
     */
    ref: string;
  };
  /**
   * Usage limits; null means no limit of that kind is declared. Token limits apply to model targets only; MCP grants are call-limited only.
   */
  limits: {
    /**
     * Token rate limit (model targets only).
     */
    tokens_per_minute?: number | null;
    /**
     * Token quota per quota_period (model targets only); set together with quota_period.
     */
    token_quota?: number | null;
    /**
     * Period of token_quota; set together with token_quota.
     */
    quota_period?: ("minute" | "hour" | "day" | "week" | "month" | "year") | null;
    /**
     * Request rate limit (model targets only).
     */
    requests_per_minute?: number | null;
    /**
     * MCP call rate limit (mcp_server targets only).
     */
    mcp_calls_per_minute?: number | null;
  };
  /**
   * Cost center usage under this grant is attributed to; null when not assigned. Restricted to characters safe in an HTTP header and a metric dimension.
   */
  cost_center?: string | null;
  /**
   * false suspends the grant without deleting it.
   */
  enabled: boolean;
  /**
   * Start of the grant; null means effective immediately.
   */
  valid_from?: string | null;
  /**
   * End of the grant (exclusive); null means open-ended.
   */
  valid_until?: string | null;
  provenance: Provenance;
}
/**
 * Where an edge or alias came from.
 */
export interface Provenance {
  method:
    | "trace_observation"
    | "observed_access"
    | "declared"
    | "embedding_similarity"
    | "steward_curation"
    | "import"
    | "unknown";
  /**
   * Lowercase identifier token (source IDs, platforms, providers, kinds).
   */
  source_id: string;
  connector_version?: string | null;
  /**
   * Version of the inference rule or model when method is inferred.
   */
  inference_version?: string | null;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  recorded_at: string;
}
/**
 * Model Context Protocol server governed as a catalog entity: endpoint, transport, protocol versions, upstream authentication and the tools it exposes. Grants (grant.schema.json) target it with call limits only. Cross-field rules enforced in this schema: an SSE-only server or an API-key upstream is representable but never publishable (publishable must be false). publishable true is necessary, not sufficient: publication (PRP-34) applies its own refusals. The generated Pydantic model does not carry these conditionals (ADR-0004); JSON Schema is the source of truth. Python validators: validate_canonical_id_fullmatch (Python re.search lets '$' match before a trailing newline; the suite re-checks every canonical ID with re.fullmatch), validate_customer_segment_matches (customer segment of every canonical ID equals customer_id), validate_timestamp_order (created_at <= updated_at), validate_mcp_tool_names_unique (tool names are unique within one server).
 */
export interface McpServer {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Stable canonical ID of this entity. Canonical ID (canonical_id.schema.json) whose type segment is 'mcp_server'. The owning domain is domain_id, as for every catalog entity.
   */
  id: string;
  entity_type: "mcp_server";
  /**
   * Monotonic document version, incremented on every accepted write.
   */
  version: number;
  /**
   * Opaque optimistic-concurrency token. A mismatch on write returns the stale_version error.
   */
  etag: string;
  /**
   * Entity lifecycle state.
   */
  lifecycle_status: "draft" | "active" | "deprecated" | "retired";
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  created_at: string;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  updated_at: string;
  /**
   * Sovereign cloud boundary. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Customer segment of the canonical ID grammar.
   */
  customer_id: string;
  /**
   * Owning domain; authorization scope anchor. Canonical ID (canonical_id.schema.json) whose type segment is 'domain'.
   */
  domain_id: string;
  /**
   * Data classification label; unknown when not yet classified.
   */
  classification?: "public" | "internal" | "confidential" | "restricted" | "unknown";
  /**
   * Azure region holding the authoritative copy; null when unknown.
   */
  residency_region?: string | null;
  attributes?: Attributes;
  /**
   * Human-readable label for a non-person entity. Never a person's name.
   */
  display_name: string;
  /**
   * Streamable HTTP endpoint: https, lowercase host, optional port, path ending in /mcp. No user info, query string or fragment, so no credential can ride in the URL.
   */
  url: string;
  /**
   * streamable_http is the current MCP transport; sse is the deprecated HTTP+SSE transport (never publishable).
   */
  transport: "streamable_http" | "sse";
  /**
   * Protocol revisions the server negotiates; empty when not yet observed.
   *
   * @maxItems 32
   *
   * Items: MCP protocol revision (YYYY-MM-DD).
   */
  protocol_versions?: string[];
  /**
   * How a caller (or a gateway in front of it) authenticates to the upstream server. No credential is ever stored here.
   */
  auth: {
    /**
     * api_key upstreams are representable but never publishable.
     */
    kind: "entra" | "managed_identity" | "none" | "api_key";
    /**
     * Entra token audience (application ID URI or client ID) for entra and managed_identity; null when not applicable or not yet known.
     */
    audience?: string | null;
  };
  /**
   * Whether the server may be published through a gateway. Must be false when transport is sse or auth.kind is api_key.
   */
  publishable: boolean;
  /**
   * Tools the server lists (tools/list); empty when not yet observed.
   *
   * @maxItems 512
   */
  tools?: {
    /**
     * Tool name as the server declares it (MCP tool name character set).
     */
    name: string;
    /**
     * Server-supplied text. Untrusted: render as plain text, never treat as instructions.
     */
    description?: string | null;
    /**
     * MCP tool annotations in snake_case. Hints are advisory and server-asserted; null means not declared. Unknown annotation keys are dropped by the mapper, not stored.
     */
    annotations?: {
      title?: string | null;
      read_only_hint?: boolean | null;
      destructive_hint?: boolean | null;
      idempotent_hint?: boolean | null;
      open_world_hint?: boolean | null;
    };
  }[];
  /**
   * Accountable owner; null when not yet assigned.
   */
  owner_id?: string | null;
  provenance: Provenance;
  tags?: Tags6;
  /**
   * Deployment environment; the same vocabulary as TelemetryEvent.environment.
   */
  environment?: "production" | "staging" | "development" | "test" | "sandbox" | "unknown";
}
