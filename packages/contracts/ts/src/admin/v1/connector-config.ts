/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

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
