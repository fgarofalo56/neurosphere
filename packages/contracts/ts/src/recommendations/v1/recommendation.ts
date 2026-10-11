/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Semantic version of this document within major 1. Within v1 only additive, optional changes are allowed (ADR-0004).
 *
 * This interface was referenced by `Recommendation`'s JSON-Schema
 * via the `definition` "schema_version".
 */
export type SchemaVersion = string;
/**
 * Canonical ID cloud:customer:source:type:id (PRP-01 clarification 7). Grammar owned by schemas/catalog/v1; duplicated here as a pattern.
 *
 * This interface was referenced by `Recommendation`'s JSON-Schema
 * via the `definition` "canonical_id".
 */
export type CanonicalId = string;
/**
 * This interface was referenced by `Recommendation`'s JSON-Schema
 * via the `definition` "opaque_id".
 */
export type OpaqueId = string;
/**
 * This interface was referenced by `Recommendation`'s JSON-Schema
 * via the `definition` "version".
 */
export type Version = string;
/**
 * RFC 3339 timestamp in UTC (Z suffix required).
 *
 * This interface was referenced by `Recommendation`'s JSON-Schema
 * via the `definition` "timestamp".
 */
export type Timestamp = string;
/**
 * Money amount as a decimal string (no floats).
 *
 * This interface was referenced by `Recommendation`'s JSON-Schema
 * via the `definition` "decimal".
 */
export type Decimal = string;
/**
 * ISO 4217 alphabetic code.
 *
 * This interface was referenced by `Recommendation`'s JSON-Schema
 * via the `definition` "currency".
 */
export type Currency = string;
/**
 * RFC 3339 full-date (UTC calendar date).
 *
 * This interface was referenced by `Recommendation`'s JSON-Schema
 * via the `definition` "date".
 */
export type Date = string;

/**
 * An evidence-backed suggestion (NS-03): kind, evidence window, coverage, uncertainty, prerequisites, projected estimate and owner. Recommendations are insights, not actions: executing one goes through the shared action executor (schemas/actions/v1). Cold start uses bounded rules rather than fabricated scores: when evidence_status is insufficient_evidence, score must be absent; when score is absent, evidence_status must be insufficient_evidence. A projected_estimate always cites price_version. candidate_duplicate is always advisory (consolidation review, never an automatic merge). Unknown numeric values are null, never 0. Rules JSON Schema cannot express: evidence_window.start < evidence_window.end (tests/contracts/validators.py::check_time_range_order); uncertainty.lower <= score <= uncertainty.upper when both present (tests/contracts/validators.py::check_recommendation_score_interval); every subject_ids and owner_id belongs to the same cloud and customer as the document (tests/contracts/validators.py::check_recommendation_same_boundary).
 */
export interface Recommendation {
  schema_version: SchemaVersion;
  recommendation_id: CanonicalId;
  cloud: "commercial" | "government";
  customer_id: string;
  /**
   * Canonical ID cloud:customer:source:type:id (PRP-01 clarification 7). Grammar owned by schemas/catalog/v1; duplicated here as a pattern.
   */
  domain_id: string;
  kind:
    | "cost_spike"
    | "latency_degradation"
    | "error_rate_degradation"
    | "unused_agent"
    | "candidate_duplicate"
    | "model_right_sizing";
  /**
   * Canonical IDs of the agents, versions or deployments the recommendation is about.
   *
   * @minItems 1
   * @maxItems 50
   */
  subject_ids: [CanonicalId, ...CanonicalId[]];
  /**
   * rule for cold-start bounded rules; statistical or ml when enough history exists.
   */
  method: "rule" | "statistical" | "ml";
  generator?: {
    generator_id: OpaqueId;
    generator_version: Version;
  };
  evidence_status: "sufficient" | "insufficient_evidence";
  /**
   * Confidence in [0, 1]. Absent on cold start (insufficient_evidence); never fabricated.
   */
  score?: number;
  evidence_window: TimeRange;
  /**
   * @maxItems 200
   */
  evidence_ids: OpaqueId[];
  coverage: Coverage;
  uncertainty: Uncertainty;
  /**
   * @maxItems 20
   */
  prerequisites: Prerequisite[];
  projected_estimate?: ProjectedEstimate;
  owner: Owner;
  /**
   * True when no supported write connector can execute the change; the recommendation is then advisory only and never a catalog-only pretend change.
   */
  advisory: boolean;
  created_at: Timestamp;
  expires_at?: Timestamp;
}
/**
 * This interface was referenced by `Recommendation`'s JSON-Schema
 * via the `definition` "time_range".
 */
export interface TimeRange {
  start: Timestamp;
  end: Timestamp;
}
/**
 * How much of the relevant population the evidence observed. observed_fraction null means unknown, never 0.
 *
 * This interface was referenced by `Recommendation`'s JSON-Schema
 * via the `definition` "coverage".
 */
export interface Coverage {
  method: "full" | "sampled" | "partial" | "unknown";
  observed_fraction: number | null;
  sampling_rate?: number | null;
  /**
   * @maxItems 100
   */
  missing_source_ids?: CanonicalId[];
}
/**
 * Uncertainty of the score or estimate. not_estimable is the honest value on cold start; it carries no bounds.
 *
 * This interface was referenced by `Recommendation`'s JSON-Schema
 * via the `definition` "uncertainty".
 */
export interface Uncertainty {
  method:
    "confidence_interval" | "credible_interval" | "bootstrap" | "rule_bound" | "not_estimable";
  lower?: number;
  upper?: number;
  level?: number;
}
/**
 * A precondition for acting on the recommendation (NS-03: compatibility, quality regression, cost comparison, staged rollout, rollback).
 *
 * This interface was referenced by `Recommendation`'s JSON-Schema
 * via the `definition` "prerequisite".
 */
export interface Prerequisite {
  kind:
    | "capability_compatibility"
    | "context_compatibility"
    | "tool_compatibility"
    | "quality_regression_test"
    | "cost_comparison"
    | "staged_rollout_plan"
    | "rollback_plan"
    | "owner_consent"
    | "approval"
    | "write_connector_available";
  status: "met" | "unmet" | "unknown";
  /**
   * @maxItems 50
   */
  evidence_ids?: OpaqueId[];
}
/**
 * Projected cost effect. Always an estimate, always cites price_version (estimated spend without a price version is invalid, matching CostRecord).
 *
 * This interface was referenced by `Recommendation`'s JSON-Schema
 * via the `definition` "projected_estimate".
 */
export interface ProjectedEstimate {
  estimate_kind: "estimated";
  period: "monthly" | "annual" | "evidence_window";
  baseline_amount: Decimal;
  projected_amount: Decimal;
  lower_amount?: Decimal;
  upper_amount?: Decimal;
  currency: Currency;
  price_version: Version;
  price_effective_date?: Date;
}
/**
 * Owner of the subject. resolution unresolved means owner_id is null (owner unknown, routed to stewards).
 *
 * This interface was referenced by `Recommendation`'s JSON-Schema
 * via the `definition` "owner".
 */
export interface Owner {
  resolution: "assigned" | "inferred" | "unresolved";
  owner_id: CanonicalId | null;
}
