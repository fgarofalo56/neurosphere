/**
 * Hand-mirrored from services/api/neurosphere_api/catalog/access/models.py (wire contract,
 * PRP-73 item 3). Results are observed or curated edges, never entitlements.
 */

export type AccessMode = "read" | "write";
export type EdgeStatus = "asserted" | "inferred" | "curated";
export type TruncatedReason = "max_assets" | "max_accessors" | "max_depth" | "timeout_ms";

export const SENSITIVITY_CATEGORIES = [
  "pii",
  "phi",
  "cui",
  "pci",
  "financial",
  "biometric",
  "credentials",
  "export_controlled",
  "legal_privileged",
  "other",
] as const;
export type SensitivityCategoryName = (typeof SENSITIVITY_CATEGORIES)[number];

export interface AccessFilters {
  readonly classifications?: readonly string[];
  readonly sensitivity_categories?: readonly SensitivityCategoryName[];
  readonly contains_personal_data?: boolean;
  readonly residency_regions?: readonly string[];
  readonly region_group?: string;
  readonly domain_ids?: readonly string[];
}

export interface AccessQueryBody {
  readonly asset_ids: readonly string[];
  readonly filters: AccessFilters;
  readonly modes: readonly AccessMode[];
  readonly include_unassessed: boolean;
}

export interface AccessBound {
  readonly max_assets: number;
  readonly max_accessors: number;
  readonly timeout_ms: number;
  readonly max_depth?: number | null;
}

export interface AccessAssetView {
  readonly id: string;
  readonly display_name: string;
  readonly domain_id: string | null;
  readonly classification: string | null;
  readonly residency_region: string | null;
  readonly contains_personal_data: boolean | null;
  readonly sensitivity_categories: readonly string[] | null;
}

export interface AccessRowView {
  readonly asset_id: string;
  readonly accessor_id: string;
  readonly accessor_type: string;
  readonly accessor_name: string;
  readonly accessor_domain_id: string | null;
  readonly mode: AccessMode | null;
  readonly relation: string;
  readonly edge_id: string;
  readonly status: EdgeStatus;
  readonly confidence: number;
  readonly provenance_method: string;
  readonly provenance_source_id: string;
  readonly evidence_ids: readonly string[];
  readonly last_observed: string;
  readonly depth: number;
  readonly relation_path: readonly string[];
  readonly path_node_ids: readonly string[];
}

interface Bounded {
  readonly truncated: boolean;
  readonly truncated_reason: TruncatedReason | null;
  readonly assets_scanned: number;
  readonly bound: AccessBound;
}

export interface AccessQueryResponse extends Bounded {
  readonly rows: readonly AccessRowView[];
  readonly assets: readonly AccessAssetView[];
  readonly unassessed_assets: readonly AccessAssetView[] | null;
  readonly unassessed_count: number | null;
}

export interface AccessDepthGroup {
  readonly depth: number;
  readonly rows: readonly AccessRowView[];
}

export interface AccessDependentsResponse extends Bounded {
  readonly groups: readonly AccessDepthGroup[];
  readonly total: number;
}

export interface RegionGroupView {
  readonly name: string;
  readonly regions: readonly string[];
}

export interface RegionGroupsResponse {
  readonly groups: readonly RegionGroupView[];
}

/** 422 reason codes the access routes return. */
export const ACCESS_REASONS = [
  "unknown_region_group",
  "unknown_region",
  "max_depth_exceeded",
  "invalid_depth",
  "too_many_assets",
] as const;
