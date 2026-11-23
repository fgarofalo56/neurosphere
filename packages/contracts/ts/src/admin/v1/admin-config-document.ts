/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * What happened; open-ended: readers must tolerate unknown values.
 *
 * This interface was referenced by `NotificationSubscription`'s JSON-Schema
 * via the `definition` "event_class".
 */
export type NotificationEventClass =
  | "policy_violation_opened"
  | "policy_violation_escalated"
  | "policy_violation_resolved"
  | "policy_exception_requested"
  | "policy_exception_decided"
  | "hitl_item_assigned"
  | "hitl_item_escalated"
  | "hitl_item_expiring"
  | "approval_requested"
  | "approval_decided"
  | "action_executed"
  | "action_failed"
  | "capture_policy_changed"
  | "enforcement_mode_changed"
  | "budget_threshold_crossed"
  | "channel_delivery_failed";
/**
 * Lowest severity delivered.
 */
export type PolicySeverity = "low" | "medium" | "high" | "critical";
/**
 * Where a decision is enforced; open-ended: readers must tolerate unknown values.
 *
 * This interface was referenced by `EnforcementBinding`'s JSON-Schema
 * via the `definition` "enforcement_point".
 */
export type EnforcementPoint =
  "gateway" | "tool_call" | "mcp_server" | "mcp_client" | "sdk" | "budget" | "registration";
/**
 * How a policy or enforcement point acts: off (not evaluated), audit (evaluated and recorded, never blocks; the default, GD-7) or enforce (blocks). Enforce is set only by an approved action.
 */
export type EnforcementMode = "off" | "audit" | "enforce";

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
   * Kind of a versioned operator configuration document (AdminConfigDocument.kind). Each kind's body is validated in core by ADMIN_KIND_MODELS (PRP-65). Open-ended: readers must tolerate unknown values.
   */
  kind:
    | "producer"
    | "connector_config"
    | "domain"
    | "budget"
    | "price_sheet"
    | "review_policy"
    | "system_setting"
    | "notification_channel"
    | "notification_subscription"
    | "enforcement_binding";
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
    | SystemSetting
    | NotificationChannel
    | NotificationSubscription
    | EnforcementBinding;
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
  /**
   * Open-ended: readers must tolerate unknown values.
   */
  connector_kind:
    | "gateway_poll"
    | "foundry_discovery"
    | "billing_export"
    | "otel"
    | "azure_monitor_ai"
    | "generic"
    | "entra_identity"
    | "purview"
    | "unity_catalog"
    | "m365_copilot"
    | "github_copilot"
    | "cursor"
    | "openai_enterprise"
    | "anthropic_claude"
    | "entra_shadow_ai"
    | "github_issues";
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
   * Permission the reviewer needs on the item's domain. Open-ended: readers must tolerate unknown values.
   */
  approver_permission: "action.approve" | "catalog.curate" | "config.manage" | "govpolicy.manage";
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
  /**
   * Open-ended: readers must tolerate unknown values.
   */
  setting_key:
    | "copilot"
    | "judge"
    | "search"
    | "scan"
    | "mcp_server"
    | "write_target"
    | "interaction_capture"
    | "notifications"
    | "enforcement";
  enabled: boolean;
  copilot?: ModelEndpointSetting;
  judge?: ModelEndpointSetting;
  search?: SearchSetting;
  scan?: ScanSetting;
  mcp_server?: McpServerSetting;
  write_target?: WriteTargetSetting;
  interaction_capture?: InteractionCaptureSetting;
  notifications?: NotificationsSetting;
  enforcement?: EnforcementSetting;
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
/**
 * Where captured interaction content is stored and how it is encrypted (PRP-99). kek_uri is a Key Vault key identifier only (https://<vault>.vault.azure.net or usgovcloudapi.net /keys/<name>[/<32 hex version>]); it is null only when kek_provider is local_development and is required when it is key_vault_key. The vault suffix must match the cloud of the deployment (tests/contracts/validators.py::check_kek_uri_cloud). Capture itself stays off until an approved capture_policy_change.
 *
 * This interface was referenced by `SystemSetting`'s JSON-Schema
 * via the `definition` "interaction_capture".
 */
export interface InteractionCaptureSetting {
  /**
   * Where the key-encryption key lives. Open-ended: readers must tolerate unknown values.
   */
  kek_provider: "key_vault_key" | "local_development";
  /**
   * Key Vault key identifier of the key-encryption key; null only for local_development.
   */
  kek_uri: string | null;
  /**
   * Azure Resource Manager resource id (/subscriptions/<guid>/resourceGroups/<name>/providers/<namespace>/<type>/<name>...).
   */
  content_storage_account_resource_id: string;
  content_container: string;
  credential: CredentialReference;
  max_content_chars_per_interaction?: number;
  shed_capture_at_queue_percent?: number;
}
/**
 * Notification sender limits and the egress allow-list (PRP-99). Hostnames only; every channel's allowed_host must be on this list at send time.
 *
 * This interface was referenced by `SystemSetting`'s JSON-Schema
 * via the `definition` "notifications".
 */
export interface NotificationsSetting {
  /**
   * @minItems 1
   * @maxItems 32
   */
  egress_allowed_hosts: [string, ...string[]];
  max_attempts?: number;
  retry_base_seconds?: number;
  dedup_window_seconds?: number;
}
/**
 * Policy decision service limits (PRP-99). The SDK guard fails open by default (owner decision GD-8); enforcement modes live on EnforcementBinding and default to audit.
 *
 * This interface was referenced by `SystemSetting`'s JSON-Schema
 * via the `definition` "enforcement".
 */
export interface EnforcementSetting {
  decision_cache_ttl_seconds?: number;
  /**
   * Open-ended: readers must tolerate unknown values.
   */
  sdk_failure_mode?: "fail_open" | "fail_closed";
  decide_rate_limit_per_minute?: number;
}
/**
 * A notification channel (PRP-99; body of admin_kind notification_channel). The endpoint is never a property of this document: it lives in Key Vault and is referenced by endpoint_credential (key_vault_secret only). The one exception is local_sink_url, a plain-HTTP loopback or compose-service URL for local development (core refuses local_sink unless NS_ENV=local). Rules the Pydantic projection drops (if/then) are pinned by tests/contracts/test_governance_a_notifications.py: local_sink requires local_sink_url and local_sink_url requires local_sink; endpoint_credential is null only with local_sink; a webhook channel needs hmac_credential unless local_sink.
 */
export interface NotificationChannel {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Lowercase operator-chosen identifier.
   */
  channel_id: string;
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
   * Human-readable label shown in the console. Not an identity attribute: never a person's name, UPN or email.
   */
  display_name: string;
  /**
   * Transport. Open-ended: readers must tolerate unknown values. email is declared; PRP-107 may ship it not_built.
   */
  kind: "webhook" | "teams_webhook" | "email";
  /**
   * The one host this channel may call: a lowercase bare hostname (no scheme, port or path), checked against the egress allow-list at send time.
   */
  allowed_host: string;
  /**
   * Key Vault secret holding the endpoint URL or transport settings. Null only when local_sink is true.
   */
  endpoint_credential?: CredentialReference | null;
  /**
   * Key Vault secret holding the webhook signing material. Required (non-null) for kind webhook unless local_sink.
   */
  hmac_credential?: CredentialReference | null;
  /**
   * Deliver to local_sink_url instead of the vaulted endpoint. Core refuses it unless NS_ENV=local (PRP-107 clarification 7).
   */
  local_sink?: boolean;
  /**
   * Plain-HTTP loopback or compose-service URL with no query string or userinfo. Present when and only when local_sink is true.
   */
  local_sink_url?: string | null;
  enabled: boolean;
}
/**
 * Which event classes reach which channel and for which audience roles (PRP-99; body of admin_kind notification_subscription). Recipients are resolved inside the sender from the roles and are never stored.
 */
export interface NotificationSubscription {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Lowercase operator-chosen identifier.
   */
  subscription_id: string;
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
   * Lowercase operator-chosen identifier.
   */
  channel_id: string;
  /**
   * @minItems 1
   * @maxItems 16
   */
  event_classes: [NotificationEventClass, ...NotificationEventClass[]];
  /**
   * Roles whose members receive the notification.
   *
   * @minItems 1
   * @maxItems 6
   *
   * Items: Platform role (NS-08). admin, security_auditor and interaction_investigator are privileged and always time-bound. Open-ended: readers must tolerate unknown values.
   */
  audience_roles: [
    (
      | "viewer"
      | "analyst"
      | "domain_steward"
      | "admin"
      | "security_auditor"
      | "interaction_investigator"
    ),
    ...(
      | "viewer"
      | "analyst"
      | "domain_steward"
      | "admin"
      | "security_auditor"
      | "interaction_investigator"
    )[],
  ];
  min_severity?: PolicySeverity;
  enabled: boolean;
}
/**
 * Binds a policy to an enforcement point and a mode (PRP-99; body of admin_kind enforcement_binding). mode defaults to audit (GD-7); enforce is set only by an approved enforcement_mode_change action. A null target means every target of that point in the domain.
 */
export interface EnforcementBinding {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Lowercase operator-chosen identifier.
   */
  binding_id: string;
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
   * Lowercase operator-chosen identifier.
   */
  policy_id: string;
  point: EnforcementPoint;
  /**
   * Specific target; null = every target of the point in the domain.
   */
  target?: TargetRef | null;
  mode?: EnforcementMode;
  /**
   * pending: not yet applied. applied: verified. failed: apply failed. drifted: verified state changed. not_supported: the point cannot enforce here.
   */
  state: "pending" | "applied" | "failed" | "drifted" | "not_supported";
  /**
   * Last action intent that changed this binding.
   */
  last_intent_id?: string | null;
  /**
   * Audit record of that change.
   */
  last_audit_id?: string | null;
  /**
   * When the applied state was last read back.
   */
  last_verified_at?: string | null;
}
/**
 * Reference to the resource an action changes or an audit record concerns. `canonical_id` uses the catalog grammar `cloud:customer:source:type:id` (Clarification 7); the pattern here mirrors it and the catalog/v1 grammar is authoritative. Python validator `validate_target_ref_matches_catalog_grammar` in tests/contracts/test_canonical_ids.py checks this pattern against the catalog ID corpus so the two cannot drift. The version being acted on is carried beside this object (ActionIntent.target_version), not inside it, so it is hashed as its own field.
 */
export interface TargetRef {
  /**
   * Cloud/customer/source qualified canonical ID of the target.
   */
  canonical_id: string;
  /**
   * Catalog entity type of the target, lowercase snake_case (for example `model_deployment`, `agent_version`).
   */
  entity_type: string;
}
