/** Wire shapes the PRP-57 pages read (from services/api/openapi.json). */

export type Cloud = "commercial" | "government";
export type ObservationKind = "gateway" | "application" | "billing";
export const OBSERVATION_KINDS: readonly ObservationKind[] = ["gateway", "application", "billing"];

export interface ProducerSourceView {
  readonly source_id: string;
  readonly observation_kind: ObservationKind;
}

export interface ProducerView {
  readonly producer_id: string;
  readonly customer_id: string;
  readonly cloud: Cloud;
  readonly sources: readonly ProducerSourceView[];
  readonly status: "active" | "disabled";
  readonly rotated_at: string | null;
  readonly version: number;
  readonly updated_at: string;
}

export interface ProducerPage {
  readonly items: readonly ProducerView[];
  readonly truncated: boolean;
}

/** The only response that carries a secret. It is read once and never cached. */
export interface ProducerSecretIssued {
  readonly producer_id: string;
  readonly secret: string;
  readonly secret_sha256: string;
  readonly issued_at: string;
  readonly shown_once: true;
}

export const CONNECTOR_KINDS = [
  "gateway_poll",
  "foundry_discovery",
  "billing_export",
  "otel",
] as const;
export type ConnectorKind = (typeof CONNECTOR_KINDS)[number];

export interface CredentialReference {
  readonly kind: "key_vault_secret" | "managed_identity";
  readonly secret_uri?: string | null;
  readonly managed_identity_client_id?: string | null;
}

export type SettingScalar = string | number | boolean;

export interface ConnectorView {
  readonly connector_id: string;
  readonly connector_kind: ConnectorKind;
  readonly domain_ids: readonly string[];
  readonly settings: Readonly<Record<string, SettingScalar>>;
  readonly credential: CredentialReference | null;
  readonly enabled: boolean;
  readonly status: string;
  readonly version: number;
  readonly updated_at: string;
  readonly updated_by: string;
  readonly warnings?: readonly string[];
}

export interface ConnectorPage {
  readonly items: readonly ConnectorView[];
}

export interface ConnectorConfigBody {
  readonly schema_version: "1.0.0";
  readonly connector_id: string;
  readonly connector_kind: ConnectorKind;
  readonly domain_ids: readonly string[];
  readonly settings: Readonly<Record<string, SettingScalar>>;
  readonly credential: CredentialReference | null;
  readonly enabled: boolean;
}

export interface MeDomain {
  readonly domain_id: string;
  readonly display_name: string;
  readonly display_name_source: "catalog" | "derived";
  readonly cloud: Cloud;
  readonly permissions: readonly string[];
}

export interface MeDomains {
  readonly items: readonly MeDomain[];
}

/** The four sources of GET /api/v1/admin/sources/status (PRP-139 item 3). */
export type SourceName = "foundry" | "apim_gateway" | "billing" | "azure_monitor_telemetry";
export type SourceState = "not_connected" | "connected_no_data" | "connected" | "failing";
export type RunState = "ok" | "partial" | "failed" | "idle" | "not_configured";
export type StatusConnectorKind = "foundry_discovery" | "gateway_poll" | "billing_export";

export interface SourceStatusRow {
  readonly source: SourceName;
  readonly state: SourceState;
  readonly last_success_at: string | null;
  readonly available: boolean;
  readonly reason?: string | null;
}

export interface ConnectorRunRow {
  readonly kind: StatusConnectorKind;
  readonly state: RunState;
  readonly reason: string | null;
  readonly last_success_at: string | null;
  readonly last_attempt_at: string | null;
  readonly counts: Readonly<Record<string, number>>;
}

export interface SourcesAdminStatus {
  readonly sources: readonly SourceStatusRow[];
  readonly connectors: readonly ConnectorRunRow[];
}
