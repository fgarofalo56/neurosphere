import type { FeatureMockContext, FeatureMockHandler } from "./context.ts";

/**
 * PRP-31 item 8 evaluations mock: GET /api/v1/evaluation/domains/{domain}/results with
 * subject_id / dimension filters and an offset cursor. Every value is SYNTHETIC. Only the
 * sandbox finance domain is readable; any other domain answers 403 (never an empty 200).
 */

export const EVAL_DOMAIN = "commercial:e2e:sandbox:domain:finance";
export const EVAL_SUBJECT_A = "commercial:e2e:catalog:model_deployment:eval-a";
export const EVAL_SUBJECT_B = "commercial:e2e:catalog:model_deployment:eval-b";
/** Results in the finance domain: more than one page at the page size the UI asks for. */
export const EVAL_TOTAL = 30;

const PATH = /^\/api\/v1\/evaluation\/domains\/([^/]+)\/results$/;
const DIMENSIONS = ["task_success", "groundedness", "safety"] as const;

function result(index: number): Record<string, unknown> {
  const dimension = DIMENSIONS[index % DIMENSIONS.length] ?? "task_success";
  const subject = index % 2 === 0 ? EVAL_SUBJECT_A : EVAL_SUBJECT_B;
  const llm = index % 3 !== 2;
  const minute = String(index % 60).padStart(2, "0");
  return {
    schema_version: "1.0.0",
    evaluation_id: `eval-${String(index).padStart(3, "0")}`,
    subject_id: subject,
    mode: "offline_benchmark",
    status: index % 7 === 6 ? "partial" : "completed",
    judge: llm
      ? {
          judge_kind: "llm_judge",
          judge_model_id: "commercial:e2e:catalog:model_deployment:judge-1",
          judge_model_version: "v3",
          judge_prompt_version: "p2",
        }
      : { judge_kind: "programmatic", program_version: "rules-1" },
    scores: [
      {
        dimension,
        value: index % 5 === 4 ? null : 0.8125,
        scale: { min: 0, max: 1 },
        uncertainty:
          index % 5 === 4
            ? { method: "not_estimable" }
            : { method: "bootstrap", lower: 0.7421875, upper: 0.8828125, level: 0.95 },
        sample_size: 40 + index,
      },
    ],
    calibration: llm
      ? {
          calibration_ref: `cal-${index}`,
          human_label_set_version: "labels-1",
          agreement: { metric: "cohen_kappa", value: 0.71, sample_size: 120 },
          calibrated_at: "2026-10-01T00:00:00.000000Z",
        }
      : null,
    completed_at: `2026-10-20T10:${minute}:00.000000Z`,
  };
}

function json(ctx: FeatureMockContext, status: number, body: unknown, type = "application/json") {
  ctx.res.writeHead(status, { "content-type": type, ...ctx.cors });
  ctx.res.end(JSON.stringify(body));
}

export const handle: FeatureMockHandler = (ctx) => {
  // The registry test passes an empty context; a handler must pass on anything it cannot read.
  const requestUrl = (ctx as { url?: URL }).url;
  if (requestUrl === undefined) return false;
  const match = PATH.exec(requestUrl.pathname);
  if (match === null) return false;
  if (ctx.req.method !== "GET") {
    json(ctx, 405, { error: "method not allowed" });
    return true;
  }
  if (!ctx.authorized) {
    json(ctx, 401, { error: "missing or unrecognised token" });
    return true;
  }
  const domain = decodeURIComponent(match[1] ?? "");
  if (domain !== EVAL_DOMAIN) {
    json(
      ctx,
      403,
      {
        schema_version: "1.0.0",
        type: "https://neurosphere.invalid/problems/forbidden",
        title: "Forbidden",
        status: 403,
        detail: "domain_out_of_scope",
        instance: requestUrl.pathname,
        code: "forbidden",
        reason: "domain_out_of_scope",
        retryable: false,
        correlation_id: ctx.correlationId,
      },
      "application/problem+json",
    );
    return true;
  }
  const params = requestUrl.searchParams;
  const subject = params.get("subject_id");
  const dimension = params.get("dimension");
  const start = Number(params.get("cursor") ?? "0");
  const size = Math.min(Number(params.get("limit") ?? "50"), 100);
  const all: Record<string, unknown>[] = [];
  for (let i = 0; i < EVAL_TOTAL; i += 1) {
    const r = result(i);
    const first = (r["scores"] as { dimension: string }[])[0];
    if (subject !== null && r["subject_id"] !== subject) continue;
    if (dimension !== null && first?.dimension !== dimension) continue;
    all.push(r);
  }
  if (!Number.isInteger(start) || start < 0 || !Number.isInteger(size) || size < 1) {
    json(ctx, 422, { error: "invalid cursor or limit" });
    return true;
  }
  const items = all.slice(start, start + size);
  const next = start + size;
  json(ctx, 200, { items, next_cursor: next < all.length ? String(next) : null });
  return true;
};
