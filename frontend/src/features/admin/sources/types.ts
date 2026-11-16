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
