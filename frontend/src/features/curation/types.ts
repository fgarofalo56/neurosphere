/** Minimal shapes of the curation responses (only the fields the page reads). */

export type EdgeStatus = "asserted" | "inferred" | "curated";
export type Decision = "accept" | "reject" | "override" | "lock" | "unlock";

export interface EdgeLock {
  readonly locked: boolean;
  readonly reason?: string | null;
  readonly expiry?: string | null;
  readonly actor?: string | null;
}

export interface EdgeValidity {
  readonly valid_from: string;
  readonly valid_to?: string | null;
}

export interface EdgeProvenance {
  readonly method: string;
  readonly source_id: string;
  readonly recorded_at?: string;
}

export interface PresentedEdge {
  readonly edge_id: string;
  readonly relation_type: string;
  readonly source_id: string;
  readonly target_id: string;
  readonly domain_id: string;
  readonly hidden: boolean;
  readonly status: EdgeStatus;
  readonly confidence: number;
  readonly validity: EdgeValidity;
  readonly lock: EdgeLock;
  readonly curation?: {
    readonly decision: string;
    readonly decided_by: string;
    readonly decided_at: string;
    readonly reason: string;
  } | null;
  readonly evidence_ids: readonly string[];
  readonly security_evidence_ids: readonly string[];
  readonly first_observed: string;
  readonly last_observed: string;
  readonly pinned: boolean;
  readonly override_ids: readonly string[];
  /** The binding the next decision needs. Absent when the service does not return it. */
  readonly version?: number | null;
  readonly etag?: string | null;
  readonly provenance?: EdgeProvenance | null;
}

export interface EdgeOverrideRecord {
  readonly id: string;
  readonly decision: Decision;
  readonly actor: string;
  readonly reason: string;
  readonly decided_at: string;
  readonly lock?: EdgeLock | null;
  readonly set_confidence?: number | null;
}

export interface OverrideHistory {
  readonly edge_id: string;
  readonly overrides: readonly EdgeOverrideRecord[];
}

export interface EdgeObservation {
  readonly id: string;
  readonly observed_at: string;
  readonly confidence: number;
  readonly provenance: EdgeProvenance;
  readonly evidence_ids: readonly string[];
  readonly security_evidence_ids: readonly string[];
}

export interface ObservationPage {
  readonly items: readonly EdgeObservation[];
  readonly next_cursor?: string | null;
}

/** Everything the browser may send for a decision. Nothing else is ever added. */
export interface DecisionBody {
  readonly decision: Decision;
  readonly reason: string;
  readonly expected_edge_version: number;
  readonly expected_edge_etag: string;
  readonly lock_expiry?: string;
  readonly set_confidence?: number;
}

export interface DecisionResult {
  readonly override: EdgeOverrideRecord;
  readonly presented: PresentedEdge;
}
