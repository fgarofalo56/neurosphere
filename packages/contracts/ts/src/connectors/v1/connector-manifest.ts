/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Registration manifest for one connector (NS-09): capabilities, permission scopes, data granularity, freshness, rate limits, credential references, advisory flag and write support. No member can hold a secret value: there is no free-text field, credentials are Key Vault secret identifiers (vault_ref) validated by pattern, and URLs cannot carry query strings, fragments or userinfo (so no SAS or signed URLs). Read-only connectors are advisory; only connectors with write support can back the action executor (PRP-17). Rules JSON Schema cannot express are checked by the Python validator check_connector_manifest in tests/contracts/test_connector_manifest.py (PRP-01 item 7): credential_refs names are unique; no pattern-constrained string (scopes, names) contains high-entropy or known secret-prefix material; a vault_ref host matches a cloud listed in supported_clouds (vault.azure.net for commercial, vault.usgovcloudapi.net for government).
 */
export interface ConnectorManifest {
  /**
   * Contract version of this document (semver within major 1).
   */
  schema_version: string;
  /**
   * Connector identifier, lowercase.
   */
  name: string;
  /**
   * Connector semantic version.
   */
  version: string;
  /**
   * HTTPS documentation URL. No query string, fragment or userinfo.
   */
  documentation_url?: string;
  /**
   * Azure clouds this connector registration may run in. A registration never moves data between clouds.
   *
   * @minItems 1
   */
  supported_clouds: ["commercial" | "government", ...("commercial" | "government")[]];
  /**
   * What the connector can provide or do.
   *
   * @minItems 1
   */
  capabilities: [
    (
      | "telemetry_ingest"
      | "cost_ingest"
      | "catalog_discovery"
      | "usage_reports"
      | "evaluation_results"
      | "audit_events"
      | "health_reporting"
      | "action_execution"
    ),
    ...(
      | "telemetry_ingest"
      | "cost_ingest"
      | "catalog_discovery"
      | "usage_reports"
      | "evaluation_results"
      | "audit_events"
      | "health_reporting"
      | "action_execution"
    )[],
  ];
  /**
   * Permission scopes or roles the connector requests (for example Reports.Read.All or https://management.azure.com/.default). Names only, never values.
   *
   * @maxItems 64
   */
  scopes: string[];
  /**
   * Finest grain of data the connector delivers.
   */
  granularity: {
    time_grain: "event" | "minute" | "hour" | "day" | "month" | "unknown";
    subject_level: "request" | "principal" | "agent" | "deployment" | "tenant" | "unknown";
  };
  /**
   * Expected delay between source event and availability, in integer milliseconds. null = unknown, never 0.
   */
  freshness: {
    typical_delay_ms: number | null;
    max_delay_ms: number | null;
  };
  /**
   * Published source rate limits; null = unknown, empty array = source publishes none.
   *
   * @maxItems 16
   */
  rate_limits: RateLimit[] | null;
  /**
   * managed_identity and workload_identity_federation carry no credential_refs; vault_reference requires at least one.
   */
  auth_mode: "managed_identity" | "workload_identity_federation" | "vault_reference";
  /**
   * Credentials by reference only. There is deliberately no field for a credential value.
   *
   * @maxItems 8
   */
  credential_refs: CredentialRef[];
  /**
   * true = recommendations from this connector are advisory only (no executable actions). Must be true exactly when write_support.supported is false.
   */
  advisory: boolean;
  write_support: WriteSupport;
}
/**
 * This interface was referenced by `ConnectorManifest`'s JSON-Schema
 * via the `definition` "rate_limit".
 */
export interface RateLimit {
  limit_scope: "per_connector" | "per_tenant" | "per_credential" | "per_principal";
  max_requests: number;
  window_ms: number;
}
/**
 * This interface was referenced by `ConnectorManifest`'s JSON-Schema
 * via the `definition` "credential_ref".
 */
export interface CredentialRef {
  /**
   * Logical credential name used by the connector code.
   */
  name: string;
  /**
   * Azure Key Vault secret identifier: https://<vault>.vault.azure.net/secrets/<name>[/<version>] or the vault.usgovcloudapi.net equivalent. Resolved at runtime by managed identity; the value never appears in a manifest, prompt or log.
   */
  vault_ref: string;
}
/**
 * This interface was referenced by `ConnectorManifest`'s JSON-Schema
 * via the `definition` "write_support".
 */
export interface WriteSupport {
  supported: boolean;
  /**
   * Action kinds the connector can execute through the shared action executor. Empty when supported is false.
   */
  actions: (
    | "model_deployment_swap"
    | "model_deployment_scale"
    | "policy_update"
    | "routing_update"
    | "agent_disable"
    | "agent_enable"
  )[];
}
