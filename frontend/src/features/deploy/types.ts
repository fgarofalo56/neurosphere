/** Wire shapes of the deploy scan/plan/capabilities endpoints (services/api deploy/*, ui_adapters). */
export interface ConsentRecord {
  readonly consent_id: string;
  readonly consented_by: string;
  readonly consented_subscriptions: readonly string[];
}

export interface ScanRequest {
  readonly consent: ConsentRecord;
  readonly subscription_ids: readonly string[];
}

export interface DiscoveredResource {
  readonly category: string;
  readonly type: string;
  readonly id: string;
  readonly name: string;
  readonly location?: string | null;
  readonly sku?: string | null;
  readonly subscription_id: string;
  readonly tags?: Readonly<Record<string, string>>;
}

export interface SubscriptionScan {
  readonly subscription_id: string;
  readonly status: "visible" | "not_visible";
  readonly resources: readonly DiscoveredResource[];
  readonly note?: string | null;
}

export interface ScanResponse {
  readonly visibility_limited: true;
  readonly visibility_note: string;
  readonly consent_id: string;
  readonly scanned_at: string;
  readonly subscriptions: readonly SubscriptionScan[];
}

export const MANIFEST_SERVICES = [
  "api_management",
  "model_endpoint",
  "key_vault",
  "monitoring",
  "event_hubs",
  "storage",
  "analytics_workspace",
  "cosmos_db",
  "ai_search",
  "container_registry",
  "kubernetes",
  "app_service",
] as const;
export type ManifestService = (typeof MANIFEST_SERVICES)[number];

/** Scan category -> manifest service it can be reused for. */
export const CATEGORY_SERVICE: Readonly<Record<string, ManifestService>> = {
  apim: "api_management",
  model_endpoint: "model_endpoint",
  key_vault: "key_vault",
  monitoring: "monitoring",
  event_hubs: "event_hubs",
  storage: "storage",
  analytics_workspace: "analytics_workspace",
};

export interface ServiceChoice {
  readonly decision: "reuse" | "create" | "skip";
  readonly resource_id?: string;
  readonly sku?: string;
  readonly fallback: "create" | "skip";
}

export interface OwnerConsentRecord {
  readonly consent_id: string;
  readonly granted: boolean;
  readonly owner_principal?: string;
  readonly resource_ids: readonly string[];
  readonly recorded_at: string;
}

export interface DeploymentProfile {
  readonly cloud: string;
  readonly regions: readonly string[];
  readonly hosting: string;
  readonly analytics: string;
  readonly features: readonly never[];
  readonly allow_preview: boolean;
}

export interface PlanRequest {
  readonly profile: DeploymentProfile;
  readonly scan: ScanResponse | null;
  readonly choices: Readonly<Record<string, ServiceChoice>>;
  readonly consents: readonly OwnerConsentRecord[];
}

export interface PlanCheck {
  readonly name: string;
  readonly outcome: "pass" | "fail" | "unknown";
  readonly reason: string;
}

export interface PlanCost {
  readonly basis: "estimated" | "no_incremental_cost" | "unknown";
  readonly monthly_amount?: string | null;
  readonly currency?: string | null;
  readonly price_version?: string | null;
  readonly summary?: string | null;
}

export interface PlanItem {
  readonly service: string;
  readonly kind: "service" | "feature";
  readonly status: "reuse" | "create" | "skip" | "needs_consent" | "disabled";
  readonly existing_resource_id?: string | null;
  readonly shared: boolean;
  readonly neurosphere_created: boolean;
  readonly checks: readonly PlanCheck[];
  readonly notes: readonly string[];
  readonly disabled_reason?: string | null;
  readonly reason_code?: string | null;
  readonly source_url?: string | null;
  readonly cost_implication: PlanCost;
}

export interface PlanResponse {
  readonly plan: {
    readonly plan_id: string;
    readonly deployment_id: string;
    readonly items: readonly PlanItem[];
    readonly capability_warnings: readonly string[];
    readonly created_at: string;
  };
  readonly manifest: unknown;
}

export interface CapabilityRow {
  readonly id: string;
  readonly service: string;
  readonly feature: string;
  readonly cloud: "commercial" | "government";
  readonly region: string;
  readonly sku: string | null;
  readonly availability: "available" | "preview" | "unavailable" | "unverified";
  readonly ga_status: "ga" | "preview" | "not_applicable" | "unverified";
  readonly authorization_scope: string;
  readonly source_url: string;
  readonly observed_on: string;
  readonly notes: string | null;
}

export interface CapabilityMatrixView {
  readonly matrix_version: string;
  readonly observed_at: string;
  readonly items: readonly CapabilityRow[];
}
