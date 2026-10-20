import type { EvaluationResult } from "@neurosphere/contracts";

export type { EvaluationResult };

export type CalibrationState = "calibrated" | "uncalibrated" | "not_applicable";

/** Mirrors services/api/neurosphere_api/evaluation/models.py. Null is unknown, never 0. */
export interface Judge {
  readonly judge_kind: "llm_judge" | "human" | "programmatic" | "hybrid";
  readonly judge_model_id: string | null;
  readonly judge_model_version: string | null;
  readonly judge_prompt_version: string | null;
  readonly program_version: string | null;
}

export interface TrendPoint {
  readonly bucket_start: string;
  readonly value: number | null;
  readonly lower: number | null;
  readonly upper: number | null;
  readonly level: number | null;
  readonly sample_size: number;
  readonly judge: Judge;
  readonly calibration_state: CalibrationState;
}

export interface Trend {
  readonly dimension: string;
  readonly points: readonly TrendPoint[];
}

export interface CoveragePoint {
  readonly stratum: string;
  readonly sampled: number;
  readonly population: number | null;
  readonly coverage_fraction: number | null;
}

export interface MissingLabels {
  readonly judged: number | null;
  readonly labelled: number | null;
  readonly missing: number | null;
}

export interface PilotGroundedRate {
  readonly value: number | null;
  readonly lower: number | null;
  readonly upper: number | null;
  readonly level: number | null;
  readonly n: number;
  readonly method: "wilson_score" | "not_estimable";
  readonly target: number;
  readonly target_label: string;
}

export interface DriftAlert {
  readonly dimension: string;
  readonly subject_id: string;
  readonly detected_at: string;
  readonly statistic: number;
  readonly threshold: number;
}

/** GET /api/v1/evaluation/domains/{domain}/quality. */
export interface QualityResponse {
  readonly trends: readonly Trend[];
  readonly coverage: readonly CoveragePoint[];
  readonly missing_labels: MissingLabels;
  readonly pilot_grounded_rate: PilotGroundedRate;
  readonly drift_alerts: readonly DriftAlert[];
}

export interface QualityParams {
  readonly domainId: string;
  readonly subjectId: string;
}
