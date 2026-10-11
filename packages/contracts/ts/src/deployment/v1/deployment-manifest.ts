/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Concrete lowercase ARM region name; global is not a deployment region.
 *
 * This interface was referenced by `DeploymentManifest`'s JSON-Schema
 * via the `definition` "region".
 */
export type Region = string;
/**
 * This interface was referenced by `DeploymentManifest`'s JSON-Schema
 * via the `definition` "utc_timestamp".
 */
export type UtcTimestamp = string;

/**
 * One customer-hosted NeuroSphere deployment plan (NS-07): a single cloud, approved regions, hosting profile, analytics backend and a reuse/create/skip decision per service with owner consent and cost implication. cloud is one scalar per manifest and no service, region or endpoint field can name another cloud, so routing Government data to Commercial is not expressible; Government manifests may list only usgov* /usdod* regions and Commercial manifests may not list them. Whether a backend, SKU or service is actually offered in the chosen cloud/region is decided by the capability matrix (CapabilityMatrixEntry, data in PRP-02), not by this schema. Rules JSON Schema cannot express are checked by the Python validator check_deployment_manifest in tests/contracts/test_deployment_manifest.py (PRP-01 item 7): each service appears at most once in services; existing_resource_id is not repeated across services.
 */
export interface DeploymentManifest {
  /**
   * Contract version of this document (semver within major 1).
   */
  schema_version: string;
  /**
   * Stable identifier of this deployment.
   */
  deployment_id: string;
  /**
   * The single Azure cloud for every service and every byte of data in this deployment. A scalar by design: there is no secondary or fallback cloud.
   */
  cloud: "commercial" | "government";
  /**
   * Approved Azure region names (lowercase ARM names, for example eastus2 or usgovvirginia). The first entry is the primary region. Must belong to cloud.
   *
   * @minItems 1
   * @maxItems 8
   */
  regions: [Region, ...Region[]];
  /**
   * aks = enterprise profile on AKS; appservice = smaller App Service profile.
   */
  hosting_profile: "aks" | "appservice";
  /**
   * Analytics adapter chosen at deployment, behind the shared capability/query contract. Availability per cloud/region comes from the capability matrix.
   */
  analytics_backend: "fabric" | "synapse" | "databricks";
  /**
   * Plan lifecycle. Once approved or applied, every reused service must carry granted owner consent.
   */
  status: "draft" | "planned" | "approved" | "applied";
  /**
   * Per-service decision. Uniqueness of service is checked by check_deployment_manifest.
   *
   * @minItems 1
   * @maxItems 64
   */
  services: [ServicePlan, ...ServicePlan[]];
  /**
   * RFC 3339 UTC timestamp.
   */
  created_at: string;
}
/**
 * This interface was referenced by `DeploymentManifest`'s JSON-Schema
 * via the `definition` "service_plan".
 */
export interface ServicePlan {
  /**
   * Platform service this decision covers.
   */
  service:
    | "api_management"
    | "model_endpoint"
    | "key_vault"
    | "monitoring"
    | "event_hubs"
    | "storage"
    | "analytics_workspace"
    | "cosmos_db"
    | "ai_search"
    | "container_registry"
    | "kubernetes"
    | "app_service";
  /**
   * reuse an existing (possibly shared) resource, create a new one with IaC, or skip.
   */
  decision: "reuse" | "create" | "skip";
  /**
   * ARM resource ID of the resource to reuse. Required for reuse, null otherwise. Shared resources are never modified or deleted on uninstall.
   */
  existing_resource_id?: string | null;
  /**
   * Why the service is skipped. Required for skip.
   */
  skip_reason?: string | null;
  owner_consent: OwnerConsent;
  cost_implication: CostImplication;
}
/**
 * Enterprise owner consent for using a (shared) resource. Always required for reuse.
 *
 * This interface was referenced by `DeploymentManifest`'s JSON-Schema
 * via the `definition` "owner_consent".
 */
export interface OwnerConsent {
  /**
   * Whether owner consent is needed for this decision.
   */
  required: boolean;
  /**
   * Whether consent has been recorded.
   */
  granted: boolean;
  /**
   * Who granted consent: pseudonymous principal reference (principal pseudonym or canonical ID), no email or display name. Null until granted.
   */
  owner_principal: string | null;
  /**
   * When consent was recorded (RFC 3339 UTC); null until granted.
   */
  recorded_at: string | null;
}
/**
 * Plan/cost implication of the decision. Unknown is null, never 0; an estimate cites its price version.
 *
 * This interface was referenced by `DeploymentManifest`'s JSON-Schema
 * via the `definition` "cost_implication".
 */
export interface CostImplication {
  /**
   * estimated = priced estimate; no_incremental_cost = reuse/skip adds no new spend; unknown = not yet priced.
   */
  basis: "estimated" | "no_incremental_cost" | "unknown";
  /**
   * Estimated monthly amount as a decimal string; null unless basis is estimated.
   */
  monthly_amount: string | null;
  /**
   * ISO 4217 code; null unless basis is estimated.
   */
  currency: string | null;
  /**
   * Price sheet version the estimate cites; null unless basis is estimated.
   */
  price_version: string | null;
  /**
   * Short human-readable explanation shown in the plan.
   */
  summary?: string;
}
