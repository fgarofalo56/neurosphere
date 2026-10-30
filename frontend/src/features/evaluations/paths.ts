/**
 * Path constants for evaluation results. Kept free of heavy imports so the app shell can
 * reference routes without loading Fluent UI.
 */
export const EVALUATION_API_PREFIX = "/api/v1/evaluation";

export const EVALUATIONS_ROUTE = "evaluations";

export function evaluationResultsPath(domain: string): string {
  return `${EVALUATION_API_PREFIX}/domains/${encodeURIComponent(domain)}/results`;
}
