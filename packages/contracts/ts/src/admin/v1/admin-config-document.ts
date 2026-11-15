/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Envelope of one versioned operator configuration document in the admin_config store (PRP-65). Partitioned by customer_id; one document per (kind, id), every accepted write increments version and replaces etag. A retired document is kept for audit and is never applied. body holds the kind's own contract document; JSON Schema validates it per kind (allOf below) and core validates it again through ADMIN_KIND_MODELS (PRP-65) because the generated Pydantic model cannot express the per-kind rule (ADR-0004 shape projection).
 */
export interface AdminConfigDocument {
  /**
   * Contract version of the document, major 1 with additive minor revisions (ADR-0004).
   */
  schema_version: string;
  /**
   * Document id, unique per customer and kind (for example the producer_id, domain slug or setting_key).
   */
  id: string;
  /**
   * Customer segment of the canonical id grammar (the tenant deployment).
   */
  customer_id: string;
  /**
   * Kind of a versioned operator configuration document (AdminConfigDocument.kind). Each kind's body is validated in core by ADMIN_KIND_MODELS (PRP-65).
   */
  kind:
    | "producer"
    | "connector_config"
    | "domain"
    | "budget"
    | "price_sheet"
    | "review_policy"
    | "system_setting";
  /**
   * Monotonic version of an operator configuration document, incremented on every accepted write.
   */
  version: number;
  /**
   * Opaque optimistic-concurrency token. A mismatch on write returns the stale_version error.
   */
  etag: string;
  /**
   * active: applied by the runtime. retired: kept for audit and history only.
   */
  status: "active" | "retired";
  /**
   * RFC 3339 timestamp in UTC (Z suffix required).
   */
  updated_at: string;
  /**
   * Pseudonymous principal that made the accepted write.
   */
  updated_by: string;
  /**
   * The kind's contract document; allOf below pins which one. Never a credential value.
   */
  body:
    | ProducerRecord
    | ConnectorConfig
    | DomainDefinition
    | SpendBudget
    | PriceSheetUpload
    | ReviewPolicyDocument
    | SystemSetting;
}
/**
 * One registered ingest producer (PRP-41). Carries every field of the ingest edge's ProducerRegistration (services/api ingest/auth.py) so the registry can be loaded from the admin_config store: the producer authenticates with Authorization: Bearer <producer_id>.<secret> and the edge compares SHA-256(secret) with secret_sha256 in constant time. Only the hash is stored; the secret is returned once, in ProducerSecretIssued. A disabled producer is refused at the edge. Rules JSON Schema cannot express (source_id values are unique) are checked by tests/contracts/validators.py::check_producer_sources_unique.
 */
export interface ProducerRecord {
  /**
   * Contract version of the document, major 1 with additive minor revisions (ADR-0004).
   */
  schema_version: string;
  /**
   * Producer identifier, the part of the bearer credential before the dot. Same grammar as ProducerRegistration.producer_id.
   */
  producer_id: string;
  /**
   * Customer segment of the canonical id grammar (the tenant deployment).
   */
  customer_id: string;
  /**
   * Azure cloud boundary. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Sources this producer may publish for, and how each source's data is observed (ProducerRegistration.sources).
   *
   * @minItems 1
   * @maxItems 64
   */
  sources: [ProducerSource, ...ProducerSource[]];
  /**
   * Lowercase hex SHA-256 of the producer secret. A digest, never the secret.
   */
  secret_sha256: string;
  status: "active" | "disabled";
  /**
   * When the current secret was issued (first issue or last rotation). Null for producers imported from a static registry file.
   */
  rotated_at: string | null;
}
/**
 * This interface was referenced by `ProducerRecord`'s JSON-Schema
 * via the `definition` "source".
 */
export interface ProducerSource {
  /**
   * Source identifier the producer publishes under (TelemetryEvent/CostRecord source_id).
   */
  source_id: string;
  observation_kind: "gateway" | "application" | "billing";
}
/**
 * Operator configuration of one connector instance (PRP-42): which connector, which domains it reports into, its bounded scalar settings and the credential it uses, by reference only. settings refuses nested objects, arrays and secret-like keys (secret, password, token, key, sas, signature, credential, connection); a credential is never a setting. Rules JSON Schema cannot express are checked by tests/contracts/validators.py::check_connector_config_cloud: every domain_id is on one cloud and a key_vault_secret credential names a vault on that cloud (check_credential_reference_cloud).
 */
export interface ConnectorConfig {
  /**
   * Contract version of the document, major 1 with additive minor revisions (ADR-0004).
   */
  schema_version: string;
  /**
   * Operator-chosen id of this connector instance, unique per customer.
   */
  connector_id: string;
  connector_kind: "gateway_poll" | "foundry_discovery" | "billing_export" | "otel";
  /**
   * Domains the connector's data is attributed to. At least one; no wildcard.
   *
   * @minItems 1
   * @maxItems 64
   *
   * Items: Canonical Domain id (type segment 'domain'). No wildcard or all-domains form exists.
   */
  domain_ids: [string, ...string[]];
  /**
   * Bounded scalar settings for the connector kind (poll interval, resource ids, endpoints). Values are strings up to 512 characters, integers or booleans; nothing nested.
   */
  settings: {
    /**
     * This interface was referenced by `undefined`'s JSON-Schema definition
     * via the `patternProperty` "^[a-z][a-z0-9_]{0,63}$".
     */
    [k: string]: string | number | boolean | undefined;
  };
  /**
   * Credential by reference (Key Vault secret or managed identity). Null when the connector needs none (for example an OTLP receiver behind the producer credential).
   */
  credential: CredentialReference | null;
  enabled: boolean;
}
/**
 * A reference to a credential, never the credential (A7). Either an Azure Key Vault secret identifier on the deployment's own cloud (vault.azure.net for Commercial, vault.usgovcloudapi.net for Government), resolved at runtime by managed identity, or the client id of a user-assigned managed identity. There is deliberately no member that can hold a secret value, connection string, SAS token or key. Rules JSON Schema cannot express (the vault host matches the cloud of the owning document) are checked by tests/contracts/validators.py::check_credential_reference_cloud.
 */
export interface CredentialReference {
  /**
   * key_vault_secret: secret_uri is required and managed_identity_client_id is absent. managed_identity: managed_identity_client_id is required and secret_uri is absent.
   */
  kind: "key_vault_secret" | "managed_identity";
  /**
   * Azure Key Vault secret identifier https://<vault>.vault.azure.net/secrets/<name>[/<version>] or the vault.usgovcloudapi.net equivalent. Same grammar as connectors/v1 credential_ref.vault_ref.
   */
  secret_uri?: string;
  /**
   * Client id (application id GUID, lowercase) of a user-assigned managed identity. An identifier, not a credential.
   */
  managed_identity_client_id?: string;
}
/**
 * Operator definition of one domain (PRP-44): the authorization scope anchor every role, grant, connector and budget names. residency_region is the ARM region the domain's data is held in (Government domains use usgov* /usdod* regions; data is never bridged across clouds). The control domain is the reserved per-customer domain that holds platform configuration actions; at most one exists per customer (checked by the PRP-44 handler). A retired domain keeps its id for audit and accepts no new data.
 */
export interface DomainDefinition {
  /**
   * Contract version of the document, major 1 with additive minor revisions (ADR-0004).
   */
  schema_version: string;
  /**
   * Canonical Domain id (type segment 'domain'). No wildcard or all-domains form exists.
   */
  domain_id: string;
  /**
   * Human-readable label shown in the console. Not an identity attribute: never a person's name, UPN or email.
   */
  display_name: string;
  /**
   * Data classification label (catalog/v1 classification vocabulary).
   */
  classification: "public" | "internal" | "confidential" | "restricted" | "unknown";
  /**
   * Lowercase ARM region name (eastus2, usgovvirginia).
   */
  residency_region: string;
  status: "active" | "retired";
  is_control_domain: boolean;
}
/**
 * A spend budget for one domain and period (PRP-44; evaluated against the cost ledger by PRP-46). Titled SpendBudget because query/v1 already exports a Budget (the query execution budget). amount is a decimal string in currency, never a float. thresholds_percent are alert points as integer percentages of amount (strictly ascending, so 50, 80, 100, 120). tags_filter narrows the budget to CostRecord rows whose tags contain every listed key and value; absent means every row of the domain. Rules JSON Schema cannot express (thresholds strictly ascending) are checked by tests/contracts/validators.py::check_budget_thresholds_ascending.
 */
export interface SpendBudget {
  /**
   * Contract version of the document, major 1 with additive minor revisions (ADR-0004).
   */
  schema_version: string;
  /**
   * Lowercase operator-chosen identifier.
   */
  budget_id: string;
  /**
   * Canonical Domain id (type segment 'domain'). No wildcard or all-domains form exists.
   */
  domain_id: string;
  period: "monthly" | "quarterly" | "annual";
  /**
   * Non-negative decimal string, up to 18 integer and 12 fractional digits; no exponent, no float.
   */
  amount: string;
  /**
   * ISO 4217 alphabetic currency code.
   */
  currency: string;
  /**
   * @minItems 1
   * @maxItems 10
   */
  thresholds_percent: [number, ...number[]];
  tags_filter?: CostTags;
}
/**
 * Absent means every cost row of the domain.
 */
export interface CostTags {
  /**
   * This interface was referenced by `CostTags`'s JSON-Schema definition
   * via the `patternProperty` "^[a-z][a-z0-9_.-]{0,62}$".
   */
  [k: string]: string | undefined;
}
/**
 * An operator-uploaded price sheet (PRP-44). Maps one to one onto core pricing PriceSnapshot minus content_hash: the server builds the snapshot with build_snapshot, which stamps the hash, so an upload can never assert its own hash. Money is a decimal string, never a float. azure_retail_prices sheets apply to commercial only and their source_url host is prices.azure.com; Commercial prices are never a fallback for Government (both enforced again by PriceSnapshot). Rules JSON Schema cannot express are checked by tests/contracts/validators.py::check_price_sheet_upload: token price rows are unique per (provider, model, model_version, kind) and a token row's unit_of_measure is 1K or 1M.
 */
export interface PriceSheetUpload {
  /**
   * Contract version of the document, major 1 with additive minor revisions (ADR-0004).
   */
  schema_version: string;
  /**
   * Lowercase operator-chosen identifier.
   */
  snapshot_id: string;
  source: "azure_retail_prices" | "provider_price_sheet";
  /**
   * Where the sheet was obtained. HTTPS, no query string or fragment.
   */
  source_url: string;
  /**
   * Calendar date YYYY-MM-DD.
   */
  retrieval_date: string;
  /**
   * Calendar date YYYY-MM-DD.
   */
  effective_date: string;
  /**
   * ISO 4217 alphabetic currency code.
   */
  currency: string;
  /**
   * @minItems 1
   * @maxItems 2
   *
   * Items: Azure cloud boundary. Government data is never bridged to Commercial.
   */
  clouds: ["commercial" | "government", ...("commercial" | "government")[]];
  /**
   * true for demo or test sheets; synthetic prices are labelled wherever they are shown.
   */
  synthetic: boolean;
  notes: string;
  /**
   * @minItems 1
   * @maxItems 10000
   */
  rows: [PriceSheetRow, ...PriceSheetRow[]];
}
/**
 * One price (core PriceRow; Retail Prices API Items[] field names in snake_case).
 *
 * This interface was referenced by `PriceSheetUpload`'s JSON-Schema
 * via the `definition` "price_row".
 */
export interface PriceSheetRow {
  /**
   * This interface was referenced by `PriceSheetUpload`'s JSON-Schema
   * via the `definition` "label".
   */
  service_name: string;
  /**
   * This interface was referenced by `PriceSheetUpload`'s JSON-Schema
   * via the `definition` "label".
   */
  sku_name: string;
  meter_id?: string | null;
  meter_name?: string | null;
  arm_region_name?: string | null;
  /**
   * This interface was referenced by `PriceSheetUpload`'s JSON-Schema
   * via the `definition` "label".
   */
  unit_of_measure: string;
  /**
   * Non-negative decimal string, up to 18 integer and 12 fractional digits; no exponent, no float.
   */
  retail_price: string;
  unit_price?: string | null;
  /**
   * This interface was referenced by `PriceSheetUpload`'s JSON-Schema
   * via the `definition` "label".
   */
  price_type?: string;
  effective_start_date?: string | null;
  token_meter?: PriceSheetTokenMeter | null;
}
/**
 * Maps a price row to a model token price (core TokenMeter).
 *
 * This interface was referenced by `PriceSheetUpload`'s JSON-Schema
 * via the `definition` "token_meter".
 */
export interface PriceSheetTokenMeter {
  /**
   * This interface was referenced by `PriceSheetUpload`'s JSON-Schema
   * via the `definition` "label".
   */
  provider: string;
  /**
   * This interface was referenced by `PriceSheetUpload`'s JSON-Schema
   * via the `definition` "label".
   */
  model: string;
  model_version?: string | null;
  kind: "input" | "output" | "cached";
}
/**
 * Operator review policy (PRP-44), mapping onto core HITL ReviewPolicyRegistry: kind_defaults become the per-review-kind defaults and action_overrides the (review_kind, action_kind) overrides. Durations are integer seconds (core ReviewPolicy timedeltas). A kind missing from kind_defaults has no policy and fails closed (capability_unavailable), so maker_checker is required. Self-approval stays forbidden unless an override says otherwise. Rules JSON Schema cannot express are checked by tests/contracts/validators.py::check_review_policy_document: review kinds in kind_defaults and (review_kind, action_kind) pairs in action_overrides are unique.
 */
export interface ReviewPolicyDocument {
  /**
   * Contract version of the document, major 1 with additive minor revisions (ADR-0004).
   */
  schema_version: string;
  /**
   * Version label copied onto every ReviewPolicy built from this document.
   */
  policy_version: string;
  /**
   * @minItems 1
   * @maxItems 16
   */
  kind_defaults: [ReviewKindDefault, ...ReviewKindDefault[]];
  /**
   * @maxItems 64
   */
  action_overrides: ReviewActionOverride[];
}
/**
 * This interface was referenced by `ReviewPolicyDocument`'s JSON-Schema
 * via the `definition` "kind_default".
 */
export interface ReviewKindDefault {
  /**
   * This interface was referenced by `ReviewPolicyDocument`'s JSON-Schema
   * via the `definition` "review_kind".
   */
  review_kind:
    "maker_checker" | "relationship" | "evaluation_dispute" | "recommendation" | "policy_exception";
  policy: ReviewPolicySettings;
}
/**
 * One core ReviewPolicy. Every duration is positive.
 *
 * This interface was referenced by `ReviewPolicyDocument`'s JSON-Schema
 * via the `definition` "policy".
 */
export interface ReviewPolicySettings {
  self_approval_forbidden: boolean;
  /**
   * Permission the reviewer needs on the item's domain.
   */
  approver_permission: "action.approve" | "catalog.curate";
  /**
   * Positive duration in whole seconds, at most 90 days.
   *
   * This interface was referenced by `ReviewPolicyDocument`'s JSON-Schema
   * via the `definition` "duration_seconds".
   */
  assignment_timeout_seconds: number;
  /**
   * Positive duration in whole seconds, at most 90 days.
   *
   * This interface was referenced by `ReviewPolicyDocument`'s JSON-Schema
   * via the `definition` "duration_seconds".
   */
  sla_seconds: number;
  /**
   * Positive duration in whole seconds, at most 90 days.
   *
   * This interface was referenced by `ReviewPolicyDocument`'s JSON-Schema
   * via the `definition` "duration_seconds".
   */
  escalation_step_seconds: number;
  max_escalations: number;
  /**
   * Positive duration in whole seconds, at most 90 days.
   *
   * This interface was referenced by `ReviewPolicyDocument`'s JSON-Schema
   * via the `definition` "duration_seconds".
   */
  expiry_seconds: number;
}
/**
 * This interface was referenced by `ReviewPolicyDocument`'s JSON-Schema
 * via the `definition` "action_override".
 */
export interface ReviewActionOverride {
  /**
   * This interface was referenced by `ReviewPolicyDocument`'s JSON-Schema
   * via the `definition` "review_kind".
   */
  review_kind:
    "maker_checker" | "relationship" | "evaluation_dispute" | "recommendation" | "policy_exception";
  /**
   * Action kind (actions/v1 ActionIntent action_kind).
   */
  action_kind: string;
  policy: ReviewPolicySettings;
}
/**
 * One runtime setting the operator manages from the console instead of environment variables (PRP-45). setting_key selects which typed member is present: exactly the member named by setting_key is set and no other. Each member holds endpoints, Azure resource ids and a CredentialReference only, never a key, token or connection string. enabled false keeps the configuration but disables the component (the first-run checklist reports it as disabled). Core validates the per-key rule again (ADMIN_KIND_MODELS, PRP-65) because the generated Pydantic model carries every member as optional.
 */
export interface SystemSetting {
  /**
   * Contract version of the document, major 1 with additive minor revisions (ADR-0004).
   */
  schema_version: string;
  setting_key: "copilot" | "judge" | "search" | "scan" | "mcp_server" | "write_target";
  enabled: boolean;
  copilot?: ModelEndpointSetting;
  judge?: ModelEndpointSetting;
  search?: SearchSetting;
  scan?: ScanSetting;
  mcp_server?: McpServerSetting;
  write_target?: WriteTargetSetting;
}
/**
 * An Azure OpenAI / Foundry model deployment used by the copilot or the evaluation judge.
 *
 * This interface was referenced by `SystemSetting`'s JSON-Schema
 * via the `definition` "model_endpoint".
 */
export interface ModelEndpointSetting {
  /**
   * HTTPS URL with no query string, fragment or userinfo (so no SAS or signed URL can be stored).
   */
  endpoint: string;
  /**
   * Model deployment name.
   */
  deployment: string;
  api_version: string;
  resource_id: string | null;
  credential: CredentialReference;
}
/**
 * Azure AI Search service and index used for catalog and evidence search.
 *
 * This interface was referenced by `SystemSetting`'s JSON-Schema
 * via the `definition` "search".
 */
export interface SearchSetting {
  /**
   * HTTPS URL with no query string, fragment or userinfo (so no SAS or signed URL can be stored).
   */
  endpoint: string;
  index_name: string;
  resource_id: string | null;
  credential: CredentialReference;
}
/**
 * Scheduled discovery scan over the listed subscriptions or resource groups.
 *
 * This interface was referenced by `SystemSetting`'s JSON-Schema
 * via the `definition` "scan".
 */
export interface ScanSetting {
  interval_seconds: number;
  /**
   * @minItems 1
   * @maxItems 64
   */
  scopes: [string, ...string[]];
  credential: CredentialReference;
}
/**
 * The NeuroSphere MCP server endpoint published to clients (PRP-22).
 *
 * This interface was referenced by `SystemSetting`'s JSON-Schema
 * via the `definition` "mcp_server".
 */
export interface McpServerSetting {
  /**
   * HTTPS URL with no query string, fragment or userinfo (so no SAS or signed URL can be stored).
   */
  endpoint: string;
  resource_id: string | null;
  credential: CredentialReference | null;
}
/**
 * Resource the action executor writes to (an API Management gateway or a Foundry project).
 *
 * This interface was referenced by `SystemSetting`'s JSON-Schema
 * via the `definition` "write_target".
 */
export interface WriteTargetSetting {
  target_kind: "apim" | "foundry";
  /**
   * Azure Resource Manager resource id (/subscriptions/<guid>/resourceGroups/<name>/providers/<namespace>/<type>/<name>...).
   */
  resource_id: string;
  credential: CredentialReference;
}
