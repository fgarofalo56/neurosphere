/**
 * Hand-mirrored from services/api/neurosphere_api/catalog/models.py, ui_adapters/ and the
 * core catalog protocol (wire contract). Only the fields the explorer reads are declared.
 */
export const ENTITY_TYPES = [
  "person",
  "agent",
  "agent_version",
  "model_deployment",
  "grounding_source",
  "tool",
  "service",
  "domain",
  "owner",
  "policy",
  "recommendation",
  "run_reference",
  "grant",
  "mcp_server",
] as const;
export type EntityTypeName = (typeof ENTITY_TYPES)[number];

export const LIFECYCLES = ["draft", "active", "deprecated", "retired"] as const;
export type LifecycleName = (typeof LIFECYCLES)[number];

export interface CatalogEntityView {
  readonly id: string;
  readonly entity_type: EntityTypeName;
  readonly domain_id: string;
  readonly version: number;
  readonly etag: string;
  readonly lifecycle_status: LifecycleName;
  readonly updated_at: string;
  readonly display_name?: string | null;
  readonly owner_kind?: string | null;
  readonly recertified_at?: string | null;
  readonly recertify_by?: string | null;
}

export interface EntityListPage {
  readonly items: readonly CatalogEntityView[];
  readonly next_cursor: string | null;
}

export interface ExportPageView {
  readonly exported_at: string;
  readonly domains: readonly string[];
  readonly items: readonly CatalogEntityView[];
  readonly next_cursor: string | null;
}

export interface PresentedEdgeView {
  readonly edge_id: string;
  readonly relation_type: string;
  readonly source_id: string;
  readonly target_id: string;
  readonly domain_id: string;
  readonly status: "asserted" | "inferred" | "curated";
  readonly confidence: number;
}

export interface GraphPathView {
  readonly node_ids: readonly string[];
  readonly edge_ids: readonly string[];
}

export interface GraphResultView {
  readonly nodes: readonly CatalogEntityView[];
  readonly edges: readonly PresentedEdgeView[];
  readonly paths: readonly GraphPathView[];
  readonly truncated: boolean;
  readonly truncated_reason: string | null;
}

export interface BudgetBody {
  readonly timeout_ms: number;
  readonly limit: number;
  readonly max_depth: number;
  readonly max_nodes?: number;
  readonly max_edges?: number;
}

export interface RecertificationItemView {
  readonly owner_id: string;
  readonly domain_id: string;
  readonly owner_kind: string;
  readonly recertified_at: string | null;
  readonly recertify_by: string;
  readonly state: "due" | "overdue";
  readonly days_until_due: number;
}

export interface RecertificationPageView {
  readonly items: readonly RecertificationItemView[];
  readonly scanned: number;
  readonly next_cursor: string | null;
}

export type RecertInclude = "due" | "overdue" | "both";

export interface StaleCandidateView {
  readonly agent_id: string;
  readonly etag: string;
  readonly domain_id: string;
  readonly last_observed: string;
}

export interface StaleAgentPlanView {
  readonly plan_id: string;
  readonly as_of: string;
  readonly window_days: number;
  readonly candidates: readonly StaleCandidateView[];
  readonly truncated: boolean;
}

export interface StaleItemResultView {
  readonly agent_id: string;
  readonly status: "marked" | "failed";
  readonly code?: string | null;
  readonly etag?: string | null;
}

export interface StaleAgentOutcomeView {
  readonly plan_id: string;
  readonly items: readonly StaleItemResultView[];
}
