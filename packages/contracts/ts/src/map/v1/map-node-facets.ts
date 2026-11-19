/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Free-form lowercase labels; at most 32, no duplicates.
 *
 * @maxItems 32
 *
 * Items: Lowercase label token used for grouping and filtering catalog entities.
 */
export type Tags = string[];
/**
 * Sensitivity categories of a data asset; empty when none are declared or not yet assessed.
 *
 * @maxItems 10
 *
 * Items: Kind of sensitive data a data asset holds; sits beside classification, not instead of it. Open-ended: readers must tolerate unknown values.
 */
export type SensitivityCategories = (
  | "pii"
  | "phi"
  | "cui"
  | "pci"
  | "financial"
  | "biometric"
  | "credentials"
  | "export_controlled"
  | "legal_privileged"
  | "other"
)[];

/**
 * Filterable facets and health of one live-map node (PRP-70 item 4). A fragment schema without schema_version, like actions/v1/target-ref, so the API and the frontend share one shape. Every member is nullable or defaulted, so none is required. Unknown numeric values (error_rate, error_count, request_count) are null, never 0: a zero means a measured zero.
 */
export interface MapNodeFacets {
  /**
   * Catalog entity type of the node; null for cluster nodes.
   */
  entity_type?:
    | (
        | "person"
        | "agent"
        | "agent_version"
        | "model_deployment"
        | "grounding_source"
        | "tool"
        | "service"
        | "domain"
        | "owner"
        | "policy"
        | "recommendation"
        | "run_reference"
        | "grant"
        | "mcp_server"
      )
    | null;
  /**
   * Deployment environment; the same vocabulary as TelemetryEvent.environment.
   */
  environment?: "production" | "staging" | "development" | "test" | "sandbox" | "unknown";
  /**
   * Cloud boundary of the node; null when unknown.
   */
  cloud?: ("commercial" | "government") | null;
  tags?: Tags;
  /**
   * Lifecycle state of the node's entity; null when unknown.
   */
  lifecycle_status?: ("draft" | "active" | "deprecated" | "retired") | null;
  /**
   * How the node came to be known: declared in the catalog, seen in telemetry, imported, or unknown.
   */
  discovery?: "declared" | "telemetry" | "import" | "unknown";
  /**
   * Observed health of the node. unknown when there is no telemetry window to judge.
   */
  health?: "ok" | "degraded" | "failing" | "unknown";
  /**
   * Share of failed requests in the window, 0 to 1; null when unknown (never 0 for unknown).
   */
  error_rate?: number | null;
  /**
   * Failed requests in the window; null when unknown (never 0 for unknown).
   */
  error_count?: number | null;
  /**
   * Requests in the window; null when unknown (never 0 for unknown).
   */
  request_count?: number | null;
  /**
   * Time of the most recent error; null when none is known.
   */
  last_error_at?: string | null;
  sensitivity_categories?: SensitivityCategories;
  /**
   * Coarse geography of the node's data; null when not declared.
   */
  residency_geography?:
    | (
        | "eu_eea"
        | "uk"
        | "switzerland"
        | "united_states"
        | "canada"
        | "asia_pacific"
        | "latin_america"
        | "middle_east_africa"
        | "other"
      )
    | null;
}
