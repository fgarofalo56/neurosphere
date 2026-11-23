/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * A CredentialReference narrowed to a Key Vault secret (a managed identity alone cannot hold an endpoint).
 *
 * This interface was referenced by `NotificationChannel`'s JSON-Schema
 * via the `definition` "key_vault_secret_reference".
 */
export type KeyVaultSecretReference = CredentialReference;

/**
 * A notification channel (PRP-99; body of admin_kind notification_channel). The endpoint is never a property of this document: it lives in Key Vault and is referenced by endpoint_credential (key_vault_secret only). The one exception is local_sink_url, a plain-HTTP loopback or compose-service URL for local development (core refuses local_sink unless NS_ENV=local). Rules the Pydantic projection drops (if/then) are pinned by tests/contracts/test_governance_a_notifications.py: local_sink requires local_sink_url and local_sink_url requires local_sink; endpoint_credential is null only with local_sink; a webhook channel needs hmac_credential unless local_sink.
 */
export interface NotificationChannel {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Channel id (slug).
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
   * The one host this channel may call: a lowercase bare DNS hostname (no scheme, port, path or IP literal; the last label starts with a letter), checked against the egress allow-list at send time.
   */
  allowed_host: string;
  /**
   * Key Vault secret holding the endpoint URL or transport settings. Null only when local_sink is true.
   */
  endpoint_credential?: KeyVaultSecretReference | null;
  /**
   * Key Vault secret holding the webhook signing material. Required (non-null) for kind webhook unless local_sink.
   */
  hmac_credential?: KeyVaultSecretReference | null;
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
