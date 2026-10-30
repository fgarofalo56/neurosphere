/** Wire shapes of GET /api/v1/evaluation/domains/{domain}/results (subset the page reads). */
export type EvaluationDimension =
  "task_success" | "groundedness" | "safety" | "tool_correctness" | "user_feedback" | "drift";

export const EVALUATION_DIMENSIONS: readonly EvaluationDimension[] = [
  "task_success",
  "groundedness",
  "safety",
  "tool_correctness",
  "user_feedback",
  "drift",
];

export interface EvaluationScore {
  readonly dimension: EvaluationDimension;
  readonly value: number | null;
  readonly scale: { readonly min: number; readonly max: number };
  readonly uncertainty: {
    readonly method: "confidence_interval" | "credible_interval" | "bootstrap" | "not_estimable";
    readonly lower?: number | null;
    readonly upper?: number | null;
    readonly level?: number | null;
    readonly standard_error?: number | null;
  };
  readonly sample_size: number;
  readonly abstained_count?: number | null;
}

export interface EvaluationJudge {
  readonly judge_kind: "llm_judge" | "human" | "programmatic" | "hybrid";
  readonly judge_model_id?: string | null;
  readonly judge_model_version?: string | null;
  readonly judge_prompt_version?: string | null;
  readonly program_version?: string | null;
}

export interface EvaluationCalibration {
  readonly calibration_ref: string;
  readonly human_label_set_version: string;
  readonly agreement: {
    readonly metric: string;
    readonly value: number;
    readonly sample_size: number;
  };
  readonly calibrated_at: string;
}

export interface EvaluationResult {
  readonly evaluation_id: string;
  readonly subject_id: string;
  readonly mode: "offline_benchmark" | "online_sampled";
  readonly status: "completed" | "partial" | "failed";
  readonly judge: EvaluationJudge;
  readonly scores: readonly EvaluationScore[];
  readonly calibration: EvaluationCalibration | null;
  readonly completed_at: string;
  readonly evidence_ids?: readonly string[] | null;
}

export interface EvaluationResultsPage {
  readonly items: readonly EvaluationResult[];
  readonly next_cursor: string | null;
}
