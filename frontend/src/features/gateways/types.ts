import type { ActionView } from "../actions/types";

export type { ActionView };

/** Hand-mirrored from services/api/neurosphere_api/gateway/ (wire contract, openapi.json). */
export type GatewayMode = "observe" | "manage";
export type GatewayCloud = "commercial" | "government";

/** Outcome of the write-permission preflight; only ARM action names, never a credential. */
export interface ModePreflight {
  readonly passed: boolean;
  readonly checked_at: string;
  /** ARM actions the APIM write connector needs at the gateway scope. */
  readonly required: readonly string[];
  /** The subset the service identity does not hold. */
  readonly missing?: readonly string[];
}

export interface GatewayRegistration {
  readonly id: string;
  readonly domain_id: string;
  readonly cloud: GatewayCloud;
  readonly name: string;
  readonly tier: string;
  readonly mode: GatewayMode;
  readonly mode_changed_at: string | null;
  readonly mode_changed_by: string | null;
  readonly mode_revision: number;
  readonly preflight: ModePreflight | null;
  /** PRP-33 observe fields. Optional so an older server response still renders. */
  readonly diagnostics?: DiagnosticsState;
  readonly last_sync_at?: string | null;
  readonly last_sync_status?: SyncStatus;
  readonly freshness_seconds?: number | null;
  readonly coverage?: number | null;
  readonly arm_resource_id?: string;
}

export type SyncStatus = "ok" | "failed" | "never";

/** Which APIM log categories the diagnostic setting sends; booleans only, never a workspace key. */
export interface DiagnosticsState {
  readonly gateway_logs?: boolean;
  readonly gateway_llm_logs?: boolean;
  readonly gateway_mcp_logs?: boolean;
}

export interface GatewayDetail extends GatewayRegistration {
  readonly inventory_counts?: Readonly<Record<string, number>> | null;
  readonly inventory_taken_at?: string | null;
}

export interface ApiEntry {
  readonly id: string;
  readonly name?: string | null;
  readonly path?: string | null;
  readonly protocols?: readonly string[];
  readonly api_type?: string | null;
  readonly subscription_required?: boolean | null;
  readonly revision?: string | null;
}

export interface OperationEntry {
  readonly api_id: string;
  readonly id: string;
  readonly method?: string | null;
  readonly url_template?: string | null;
}

export interface ProductEntry {
  readonly id: string;
  readonly name?: string | null;
  readonly state?: string | null;
  readonly subscription_required?: boolean | null;
  readonly approval_required?: boolean | null;
}

export interface PoolMember {
  readonly backend_id: string;
  readonly weight?: number | null;
  readonly priority?: number | null;
}

export interface CircuitBreakerRule {
  readonly name?: string | null;
  readonly trip_duration?: string | null;
  readonly failure_count?: number | null;
  readonly failure_interval?: string | null;
  readonly status_codes?: readonly string[];
}

export interface BackendEntry {
  readonly id: string;
  readonly type: "Single" | "Pool";
  readonly url?: string | null;
  readonly pool_members?: readonly PoolMember[];
  readonly circuit_breaker_rules?: readonly CircuitBreakerRule[];
}

export interface PolicyFragmentEntry {
  readonly name: string;
  readonly description?: string | null;
}

/** Subscription metadata only: the API never returns keys. */
export interface SubscriptionEntry {
  readonly id: string;
  readonly display_name?: string | null;
  readonly scope?: string | null;
  readonly state?: string | null;
}

export interface GatewayInventory {
  readonly gateway_id: string;
  readonly taken_at: string;
  readonly apis: readonly ApiEntry[];
  readonly operations: readonly OperationEntry[];
  readonly products: readonly ProductEntry[];
  readonly product_api_links: readonly { readonly product_id: string; readonly api_id: string }[];
  readonly backends: readonly BackendEntry[];
  readonly policy_fragments: readonly PolicyFragmentEntry[];
  readonly subscriptions: readonly SubscriptionEntry[];
}

export interface GatewayRef {
  readonly domainId: string;
  readonly gatewayId: string;
}

export interface GatewayList {
  readonly items: readonly GatewayRegistration[];
  readonly next_cursor: string | null;
}

export interface GatewayListParams {
  readonly domainId: string;
}

/** Body of POST .../mode. No identity, customer or domain fields: the server derives them. */
export interface ModeChangeRequest {
  readonly mode: GatewayMode;
  readonly idempotency_key: string;
  readonly channel: "button";
}

export interface ModeChangeVars {
  readonly domainId: string;
  readonly gatewayId: string;
  readonly request: ModeChangeRequest;
}
