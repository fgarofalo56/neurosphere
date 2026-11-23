/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

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
