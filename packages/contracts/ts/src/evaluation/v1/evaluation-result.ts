/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * Semantic version of this document within major 1. Within v1 only additive, optional changes are allowed (ADR-0004).
 *
 * This interface was referenced by `EvaluationResult`'s JSON-Schema
 * via the `definition` "schema_version".
 */
export type SchemaVersion = string;
/**
 * This interface was referenced by `EvaluationResult`'s JSON-Schema
 * via the `definition` "opaque_id".
 */
export type OpaqueId = string;
/**
 * This interface was referenced by `EvaluationResult`'s JSON-Schema
 * via the `definition` "version".
 */
export type Version = string;
/**
 * Non-negative count; null means unknown, never 0.
 *
 * This interface was referenced by `EvaluationResult`'s JSON-Schema
 * via the `definition` "nullable_count".
 */
export type NullableCount = number | null;
/**
 * RFC 3339 timestamp in UTC (Z suffix required).
 *
 * This interface was referenced by `EvaluationResult`'s JSON-Schema
 * via the `definition` "timestamp".
 */
export type Timestamp = string;
/**
 * Money amount as a decimal string (no floats).
 *
 * This interface was referenced by `EvaluationResult`'s JSON-Schema
 * via the `definition` "decimal".
 */
export type Decimal = string;
/**
 * Canonical ID cloud:customer:source:type:id (PRP-01 clarification 7). Grammar owned by schemas/catalog/v1; duplicated here as a pattern.
 *
 * This interface was referenced by `EvaluationResult`'s JSON-Schema
 * via the `definition` "canonical_id".
 */
export type CanonicalId = string;

/**
 * Result of an offline benchmark or a sampled online evaluation of one subject (NS-03). Datasets, rubrics and judges are versioned; every score reports uncertainty and sample size; sampling coverage is explicit; an LLM judge requires a calibration reference against human labels. Quality is not inferred from feedback alone: a run whose only dimension is user_feedback is rejected. Unknown values are null, never 0. Evaluation runs on approved, redacted or synthetic data inside the selected cloud boundary (data_handling). Rules JSON Schema cannot express: started_at <= completed_at and sampling.window.start < sampling.window.end (tests/contracts/validators.py::check_evaluation_times); score.value and uncertainty bounds within score.scale (tests/contracts/validators.py::check_evaluation_score_scale); sampling.sample_size <= sampling.population_size when known (tests/contracts/validators.py::check_evaluation_sampling_counts).
 */
export interface EvaluationResult {
  schema_version: SchemaVersion;
  evaluation_id: OpaqueId;
  cloud: "commercial" | "government";
  customer_id: string;
  /**
   * Canonical Domain ID used for scope filtering against the server-derived IdentityScope.
   */
  domain_id: string;
  /**
   * Canonical ID of the evaluated AgentVersion or ModelDeployment.
   */
  subject_id: string;
  mode: "offline_benchmark" | "online_sampled";
  /**
   * partial means some items were not scored (budget exhausted, abstentions); coverage shows how many.
   */
  status: "completed" | "partial" | "failed";
  /**
   * Versioned dataset; for online_sampled this is the versioned sampling frame definition.
   */
  dataset: {
    dataset_id: OpaqueId;
    dataset_version: Version;
  };
  rubric: {
    rubric_id: OpaqueId;
    rubric_version: Version;
  };
  judge: Judge;
  /**
   * @minItems 1
   * @maxItems 32
   */
  scores: [Score, ...Score[]];
  sampling: Sampling;
  /**
   * Calibration of the judge against human labels. Required (non-null) when judge.judge_kind is llm_judge or hybrid; null otherwise allowed.
   */
  calibration: Calibration | null;
  data_handling: {
    data_state: "redacted" | "approved" | "synthetic";
    /**
     * Cloud boundary the evaluation (including any judge model) ran in; must equal cloud.
     */
    boundary_cloud: "commercial" | "government";
  };
  evaluator_usage?: EvaluatorUsage;
  /**
   * @maxItems 200
   */
  evidence_ids?: OpaqueId[];
  started_at: Timestamp;
  completed_at: Timestamp;
}
/**
 * This interface was referenced by `EvaluationResult`'s JSON-Schema
 * via the `definition` "judge".
 */
export interface Judge {
  judge_kind: "llm_judge" | "human" | "programmatic" | "hybrid";
  /**
   * Model deployment canonical ID of the LLM judge.
   */
  judge_model_id?: string;
  judge_model_version?: Version;
  judge_prompt_version?: Version;
  /**
   * Version of the programmatic scorer.
   */
  program_version?: string;
}
/**
 * This interface was referenced by `EvaluationResult`'s JSON-Schema
 * via the `definition` "score".
 */
export interface Score {
  dimension:
    "task_success" | "groundedness" | "safety" | "tool_correctness" | "user_feedback" | "drift";
  /**
   * Null when the dimension could not be scored; never 0 by default.
   */
  value: number | null;
  scale: {
    min: number;
    max: number;
  };
  uncertainty: Uncertainty;
  /**
   * Items scored for this dimension.
   */
  sample_size: number;
  abstained_count?: NullableCount;
}
/**
 * This interface was referenced by `EvaluationResult`'s JSON-Schema
 * via the `definition` "uncertainty".
 */
export interface Uncertainty {
  method: "confidence_interval" | "credible_interval" | "bootstrap" | "not_estimable";
  lower?: number;
  upper?: number;
  level?: number;
  standard_error?: number;
}
/**
 * Sampling coverage. coverage_fraction null means unknown.
 *
 * This interface was referenced by `EvaluationResult`'s JSON-Schema
 * via the `definition` "sampling".
 */
export interface Sampling {
  method: "full" | "uniform_random" | "stratified" | "targeted";
  rate?: number;
  sample_size: number;
  population_size: NullableCount;
  coverage_fraction: number | null;
  window: {
    start: Timestamp;
    end: Timestamp;
  };
}
/**
 * This interface was referenced by `EvaluationResult`'s JSON-Schema
 * via the `definition` "calibration".
 */
export interface Calibration {
  /**
   * ID of the calibration run against human labels.
   */
  calibration_ref: string;
  human_label_set_version: Version;
  agreement: {
    metric: "cohen_kappa" | "krippendorff_alpha" | "spearman" | "accuracy";
    value: number;
    sample_size: number;
  };
  /**
   * @maxItems 10
   */
  bias_checks?: {
    check: "position_bias" | "verbosity_bias" | "self_preference_bias" | "length_bias";
    result: "passed" | "failed" | "not_run";
    value?: number | null;
  }[];
  calibrated_at: Timestamp;
}
/**
 * Evaluator token and cost consumption against its budget. Estimated cost always cites price_version.
 *
 * This interface was referenced by `EvaluationResult`'s JSON-Schema
 * via the `definition` "evaluator_usage".
 */
export interface EvaluatorUsage {
  judge_input_tokens: NullableCount;
  judge_output_tokens: NullableCount;
  estimated_cost?: {
    amount: Decimal;
    currency: string;
    price_version: Version;
  };
}
