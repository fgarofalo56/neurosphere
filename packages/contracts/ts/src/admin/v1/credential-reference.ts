/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

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
