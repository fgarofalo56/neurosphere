import type { FeatureMockContext, FeatureMockHandler } from "./context.ts";

/**
 * PRP-75 item 2 mock: the PRP-72 agent and tool match routes under
 * `/api/v1/recommendations/domains/{d}/match`:
 *
 * - `POST .../match` answers `AgentMatchView` `{match, assessments, confidence_note}`; `match` is the
 *   PRP-70 `AgentMatchResponse`. Fixed task texts pick the variant (normal, partial, empty).
 * - `POST .../match/feedback` answers 202 `FeedbackAccepted`; the decision is kept in module memory
 *   per principal and domain, a later decision for the same match and entity replaces the earlier.
 * - `GET .../match/metrics` answers `MatchMetricsView` computed from that memory. No route reads a
 *   decision back, so the accept count is how a spec observes "accept, reload, still accepted".
 * - `GET /api/v1/catalog/completeness` answers 404: PRP-76 is not built.
 *
 * Persona gate (a stand-in for the API's `data.read` check): the `viewer` and `nodomain` personas
 * and any domain the stub caller cannot read answer 403 with a reason code. Every id is SYNTHETIC.
 * State is module-level; a spec that changes it calls `resetAgentMatch()`.
 */

const MATCH_PATH = /^\/api\/v1\/recommendations\/domains\/([^/]+)\/match(\/feedback|\/metrics)?$/;
const COMPLETENESS_PATH = "/api/v1/catalog/completeness";

export const MATCH_TASK_TEXT = "Summarize the quarterly invoice documents for the finance team";
/** Answers a partial result: two candidates, `truncated` true, `partial_reason` "limit". */
export const MATCH_PARTIAL_TASK_TEXT =
  "Triage a large backlog of support tickets across every queue";
/** Answers zero candidates. */
export const MATCH_EMPTY_TASK_TEXT = "Translate legacy mainframe copybooks into Cobol";
export const MATCH_TELEMETRY_ENTITY = "commercial:e2e:sandbox:agent:invoice-summarizer";
export const MATCH_GRAPH_ENTITY = "commercial:e2e:sandbox:agent:finance-router";
export const MATCH_COLD_START_ENTITY = "commercial:e2e:sandbox:agent:ledger-helper-preview";
/** Entities the graph-proximity candidate is related to. */
export const MATCH_GRAPH_RELATED = [
  "commercial:e2e:sandbox:agent:invoice-summarizer",
  "commercial:e2e:sandbox:tool:ledger-search",
] as const;
export const MATCH_COLD_START_SIGNALS = ["historical_success", "latency", "usage"] as const;
export const MATCH_REASON_VIEWER = "data_read_required";
export const MATCH_REASON_DOMAIN = "domain_not_readable";
export const MATCH_REASON_UNKNOWN_MATCH = "match_not_found";
export const MATCH_REASON_UNKNOWN_CANDIDATE = "entity_not_in_match";
export const MATCH_CONFIDENCE_NOTE =
  "confidence is a relative 0-1 value derived from the score, the share of weight that was " +
  "observed and the margin to the next candidate; it is not a probability";

type SignalName =
  | "capability_match"
  | "tag_match"
  | "text_match"
  | "graph_proximity"
  | "historical_success"
  | "latency"
  | "usage"
  | "feedback_prior";

const WEIGHTS: Readonly<Record<SignalName, number>> = {
  capability_match: 0.25,
  tag_match: 0.1,
  text_match: 0.15,
  graph_proximity: 0.1,
  historical_success: 0.15,
  latency: 0.05,
  usage: 0.1,
  feedback_prior: 0.1,
};

interface Fixture {
  entity_id: string;
  entity_type: "agent" | "tool";
  display_name: string;
  values: Record<SignalName, number | null>;
  capabilities: string[];
  tags: string[];
  relations: { relation_type: string; entity_id: string; direction: string }[];
  evidence_ids: string[];
  confidence: number;
  cold_start: boolean;
}

const FIXTURES: readonly Fixture[] = [
  {
    entity_id: MATCH_TELEMETRY_ENTITY,
    entity_type: "agent",
    display_name: "Invoice Summarizer",
    values: {
      capability_match: 0.9,
      tag_match: 0.8,
      text_match: 0.85,
      graph_proximity: 0.4,
      historical_success: 0.92,
      latency: 0.7,
      usage: 0.8,
      feedback_prior: 0.6,
    },
    capabilities: ["document.summarize", "finance.invoice"],
    tags: ["finance", "invoices"],
    relations: [
      {
        relation_type: "uses_model",
        entity_id: "commercial:e2e:sandbox:model:gpt-e2e",
        direction: "outgoing",
      },
    ],
    evidence_ids: ["trace:invoice-summarizer-0001", "trace:invoice-summarizer-0002"],
    confidence: 0.86,
    cold_start: false,
  },
  {
    entity_id: MATCH_GRAPH_ENTITY,
    entity_type: "agent",
    display_name: "Finance Router",
    values: {
      capability_match: 0.5,
      tag_match: 0.6,
      text_match: 0.4,
      graph_proximity: 0.95,
      historical_success: 0.55,
      latency: 0.6,
      usage: 0.5,
      feedback_prior: 0.4,
    },
    capabilities: ["finance.invoice"],
    tags: ["finance"],
    relations: [
      { relation_type: "delegates_to", entity_id: MATCH_GRAPH_RELATED[0], direction: "outgoing" },
      { relation_type: "invokes", entity_id: MATCH_GRAPH_RELATED[1], direction: "outgoing" },
    ],
    evidence_ids: ["trace:finance-router-0001"],
    confidence: 0.58,
    cold_start: false,
  },
  {
    entity_id: MATCH_COLD_START_ENTITY,
    entity_type: "agent",
    display_name: "Ledger Helper (preview)",
    values: {
      capability_match: 0.6,
      tag_match: 0.3,
      text_match: 0.35,
      graph_proximity: 0.1,
      historical_success: null,
      latency: null,
      usage: null,
      feedback_prior: 0.2,
    },
    capabilities: ["finance.ledger"],
    tags: ["finance"],
    relations: [],
    evidence_ids: [],
    confidence: 0.21,
    cold_start: true,
  },
];

const round = (n: number): number => Math.round(n * 10_000) / 10_000;

function candidate(f: Fixture, rank: number): Record<string, unknown> {
  const signals = (Object.keys(WEIGHTS) as SignalName[]).map((signal) => {
    const value = f.values[signal];
    return {
      signal,
      value,
      weight: WEIGHTS[signal],
      contribution: value === null ? 0 : round(value * WEIGHTS[signal]),
      detail_code: value === null ? "no_observations" : null,
      evidence_ids: [],
    };
  });
  const score = round(signals.reduce((sum, s) => sum + s.contribution, 0));
  return {
    rank,
    entity_id: f.entity_id,
    entity_type: f.entity_type,
    display_name: f.display_name,
    lifecycle_status: "active",
    score,
    signals,
    matched_capabilities: f.capabilities,
    matched_tags: f.tags,
    relations: f.relations,
    evidence_ids: f.evidence_ids,
  };
}

function fixturesFor(task: string): { picked: Fixture[]; partial: boolean } {
  if (task.trim() === MATCH_EMPTY_TASK_TEXT) return { picked: [], partial: false };
  if (task.trim() === MATCH_PARTIAL_TASK_TEXT)
    return { picked: FIXTURES.slice(0, 2), partial: true };
  return { picked: [...FIXTURES], partial: false };
}

interface MatchRecord {
  readonly key: string;
  readonly entityIds: readonly string[];
}

const matches = new Map<string, MatchRecord>();
/** Per principal+domain: count of match POSTs. */
const matchCounts = new Map<string, number>();
/** Per principal+domain: `${matchId}|${entityId}` to the current decision. */
const decisions = new Map<string, Map<string, "accepted" | "rejected">>();
let sequence = 0;

/** Clears match and feedback memory (a spec that mutates state calls this in `beforeEach`). */
export function resetAgentMatch(): void {
  matches.clear();
  matchCounts.clear();
  decisions.clear();
  sequence = 0;
}

function json(
  ctx: FeatureMockContext,
  status: number,
  body: unknown,
  type = "application/json",
): void {
  ctx.res.writeHead(status, { "content-type": type, ...ctx.cors });
  ctx.res.end(JSON.stringify(body));
}

function problem(ctx: FeatureMockContext, status: number, code: string, reason: string): void {
  json(
    ctx,
    status,
    {
      schema_version: "1.0.0",
      type: `https://neurosphere.invalid/problems/${code.replaceAll("_", "-")}`,
      title: reason,
      status,
      detail: reason,
      instance: ctx.url.pathname,
      code,
      reason,
      retryable: false,
      correlation_id: ctx.correlationId,
    },
    "application/problem+json",
  );
}

async function readJson(ctx: FeatureMockContext): Promise<Record<string, unknown> | null> {
  try {
    const parsed: unknown = JSON.parse(await ctx.readBody());
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

const SCHEMA_VERSION = /^1\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/;
// eslint-disable-next-line no-control-regex
const CONTROL = /[\u0000-\u0008\u000b-\u001f\u007f]/;
const REQUEST_KEYS = new Set([
  "schema_version",
  "task_text",
  "candidate_types",
  "required_capabilities",
  "preferred_tags",
  "context_entity_ids",
  "environment",
  "limit",
  "max_graph_depth",
]);

/** The first violation of the PRP-70 `AgentMatchRequest` rules this mock enforces, or null. */
function requestFault(body: Record<string, unknown> | null): string | null {
  if (body === null) return "request body must be a JSON object";
  for (const key of Object.keys(body)) {
    if (!REQUEST_KEYS.has(key)) return `unknown field ${key}`;
  }
  if (typeof body["schema_version"] !== "string" || !SCHEMA_VERSION.test(body["schema_version"])) {
    return "schema_version is required";
  }
  const task = body["task_text"];
  if (typeof task !== "string" || task.length < 3 || task.length > 2000 || CONTROL.test(task)) {
    return "task_text must be 3 to 2000 characters without control characters";
  }
  const limit = body["limit"];
  if (
    limit !== undefined &&
    (!Number.isInteger(limit) || (limit as number) < 1 || (limit as number) > 50)
  ) {
    return "limit must be an integer from 1 to 50";
  }
  const types = body["candidate_types"];
  if (
    types !== undefined &&
    (!Array.isArray(types) ||
      types.length < 1 ||
      types.length > 2 ||
      types.some((t) => t !== "agent" && t !== "tool"))
  ) {
    return "candidate_types must list agent and or tool";
  }
  return null;
}

const REASONS = new Set([
  "not_relevant",
  "missing_capability",
  "poor_quality",
  "unavailable",
  "policy",
  "other",
]);
const CANONICAL = /^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+$/;

function feedbackFault(body: Record<string, unknown> | null): string | null {
  if (body === null) return "request body must be a JSON object";
  const allowed = new Set(["schema_version", "match_id", "entity_id", "decision", "reason_code"]);
  for (const key of Object.keys(body)) if (!allowed.has(key)) return `unknown field ${key}`;
  if (typeof body["schema_version"] !== "string" || !SCHEMA_VERSION.test(body["schema_version"])) {
    return "schema_version is required";
  }
  if (typeof body["match_id"] !== "string" || body["match_id"] === "")
    return "match_id is required";
  if (typeof body["entity_id"] !== "string" || !CANONICAL.test(body["entity_id"])) {
    return "entity_id must be a canonical id";
  }
  if (body["decision"] !== "accepted" && body["decision"] !== "rejected") {
    return "decision must be accepted or rejected";
  }
  const reason = body["reason_code"];
  if (
    reason !== undefined &&
    reason !== null &&
    !(typeof reason === "string" && REASONS.has(reason))
  ) {
    return "reason_code is not a known code";
  }
  return null;
}

const STAMP = "2026-11-10T09:00:00Z";

async function matchRoute(ctx: FeatureMockContext, key: string, domain: string): Promise<void> {
  const body = await readJson(ctx);
  const fault = requestFault(body);
  if (fault !== null || body === null)
    return problem(ctx, 422, "invalid_schema", fault ?? "invalid");
  const { picked, partial } = fixturesFor(String(body["task_text"]));
  sequence += 1;
  const matchId = `mock-match-${String(sequence).padStart(4, "0")}`;
  const cold = picked.some((f) => f.cold_start);
  matches.set(matchId, { key, entityIds: picked.map((f) => f.entity_id) });
  matchCounts.set(key, (matchCounts.get(key) ?? 0) + 1);
  const ranked = picked
    .map((f) => ({ f, c: candidate(f, 0) }))
    .sort((a, b) => (b.c["score"] as number) - (a.c["score"] as number))
    .map(({ f, c }, i) => ({ f, c: { ...c, rank: i + 1 } }));
  json(ctx, 200, {
    match: {
      schema_version: "1.0.0",
      match_id: matchId,
      domain_id: domain,
      generated_at: STAMP,
      ranker: { ranker_id: "weighted-signals", ranker_version: "1.0.0" },
      cold_start: cold,
      signals_unavailable: cold ? [...MATCH_COLD_START_SIGNALS] : [],
      candidates: ranked.map((r) => r.c),
      truncated: partial,
      partial_reason: partial ? "limit" : null,
    },
    assessments: ranked.map((r) => ({
      entity_id: r.f.entity_id,
      confidence: r.f.confidence,
      cold_start: r.f.cold_start,
    })),
    confidence_note: MATCH_CONFIDENCE_NOTE,
  });
}

async function feedbackRoute(ctx: FeatureMockContext, key: string): Promise<void> {
  const body = await readJson(ctx);
  const fault = feedbackFault(body);
  if (fault !== null || body === null)
    return problem(ctx, 422, "invalid_schema", fault ?? "invalid");
  const matchId = String(body["match_id"]);
  const entityId = String(body["entity_id"]);
  const record = matches.get(matchId);
  if (record === undefined || record.key !== key) {
    return problem(ctx, 403, "forbidden", MATCH_REASON_UNKNOWN_MATCH);
  }
  if (!record.entityIds.includes(entityId)) {
    return problem(ctx, 403, "forbidden", MATCH_REASON_UNKNOWN_CANDIDATE);
  }
  const decision = body["decision"] as "accepted" | "rejected";
  const store = decisions.get(key) ?? new Map<string, "accepted" | "rejected">();
  store.set(`${matchId}|${entityId}`, decision);
  decisions.set(key, store);
  json(ctx, 202, {
    match_id: matchId,
    entity_id: entityId,
    decision,
    decided_at: STAMP,
  });
}

function metricsRoute(ctx: FeatureMockContext, key: string, domain: string): void {
  const store = decisions.get(key) ?? new Map<string, "accepted" | "rejected">();
  let accepts = 0;
  let rejects = 0;
  const withFeedback = new Set<string>();
  for (const [k, decision] of store) {
    withFeedback.add(k.split("|")[0] ?? "");
    if (decision === "accepted") accepts += 1;
    else rejects += 1;
  }
  const total = accepts + rejects;
  json(ctx, 200, {
    domain_id: domain,
    window_start: "2026-10-11T09:00:00Z",
    window_end: STAMP,
    matches: matchCounts.get(key) ?? 0,
    matches_with_feedback: withFeedback.size,
    accepts,
    rejects,
    acceptance_rate: total === 0 ? null : round(accepts / total),
  });
}

export const handle: FeatureMockHandler = (ctx) => {
  // The registry test passes an empty context; a handler must pass on anything it cannot read.
  if ((ctx as { url?: URL }).url === undefined) return false;
  const method = ctx.req.method ?? "GET";
  if (ctx.url.pathname === COMPLETENESS_PATH) {
    if (method !== "GET") return false;
    problem(ctx, 404, "not_found", "catalog_completeness_not_available");
    return true;
  }
  const hit = MATCH_PATH.exec(ctx.url.pathname);
  if (hit === null) return false;
  const sub = hit[2] ?? "";
  const expected = sub === "/metrics" ? "GET" : "POST";
  if (method !== expected) return false;
  if (!ctx.authorized) {
    json(ctx, 401, { error: "missing or unrecognised token" });
    return true;
  }
  const domain = decodeURIComponent(hit[1] ?? "");
  if (ctx.role === "viewer" || ctx.role === "nodomain") {
    problem(ctx, 403, "forbidden", MATCH_REASON_VIEWER);
    return true;
  }
  if (!ctx.readableDomains.includes(domain)) {
    problem(ctx, 403, "forbidden", MATCH_REASON_DOMAIN);
    return true;
  }
  const key = `${ctx.role ?? "anonymous"}|${domain}`;
  if (sub === "") void matchRoute(ctx, key, domain);
  else if (sub === "/feedback") void feedbackRoute(ctx, key);
  else metricsRoute(ctx, key, domain);
  return true;
};
