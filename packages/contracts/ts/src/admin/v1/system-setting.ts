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
