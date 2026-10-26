/**
 * PRP-19 mock endpoints: /api/v1/copilot/** and /api/v1/reports/**. Shapes follow the wire
 * contract in PRPs/active/PRP-19 ("Wire contract") and the API models in
 * services/api/neurosphere_api/{copilot,reports}/models.py; every identity and number is SYNTHETIC.
 *
 * The mock only imitates OUTCOMES the real API owns (401 without a token, 403 for a domain the
 * stub caller cannot read, 404 for an unknown or foreign conversation, If-Match on writes that
 * require it). Chat never executes anything: an `action_suggestion` carries the id of a DRAFTED
 * intent that the PRP-17 mock (`/api/v1/actions/domains/{domain}/intents/{id}`) already serves, so
 * the confirmation dialog can load it.
 *
 * Streaming fixtures (POST .../conversations/{id}/messages -> text/event-stream). Select one with
 * the `fixture` query parameter (`?fixture=abstain`) or by message text: `fixture:<name>` anywhere
 * in the text, else a keyword (abstain, denied, swap/action, error); anything else is `answered`.
 * The first `token` is written immediately after `context` and `tool` (no artificial delay before
 * it) so first-token latency can be measured; later tokens are paced a few ms apart.
 */
import { randomUUID } from "node:crypto";
import type { IncomingMessage, ServerResponse } from "node:http";
import { DEMO_REPORT_TITLES } from "./demoProfile.ts";

export const COPILOT_PATH = /^\/api\/v1\/copilot\/(.*)$/;
export const REPORTS_PATH = /^\/api\/v1\/reports\/(.*)$/;

export const FIXTURE_NAMES = [
  "answered",
  "abstain",
  "denied",
  "action_suggestion",
  "error",
] as const;
export type FixtureName = (typeof FIXTURE_NAMES)[number];

/** Delay between streamed tokens after the first (ms). The first token has none. */
export const TOKEN_PACE_MS = 12;
export const MOCK_OWNER = "commercial:e2e:entra:person:psn_mock_caller";
const OTHER_OWNER = "commercial:e2e:entra:person:psn_mock_other0";
const NOW = "2026-10-21T12:00:00Z";
const STALE_AS_OF = "2026-10-14T12:00:00Z";
const EXPIRES = "2026-11-20T12:00:00Z";
export const REPORT_SEED_OWN = "rpt-seed-own";
export const REPORT_SEED_PENDING = "rpt-seed-pending";
export const REPORT_SEED_APPROVED = "rpt-seed-approved";

export interface CopilotSuggestion {
  readonly intent_id: string;
  readonly domain_id: string;
  readonly action_type: string;
  readonly target: Record<string, unknown>;
  readonly intent_hash: string;
}

export interface CopilotMockContext {
  readonly req: IncomingMessage;
  readonly res: ServerResponse;
  readonly url: URL;
  readonly cors: Record<string, string>;
  readonly readBody: () => Promise<string>;
  readonly authorized: boolean;
  /** Domains the stub caller may read; anything else is a 403 problem. */
  readonly readableDomains: readonly string[];
  /** The drafted PRP-17 intent the `action_suggestion` fixture points at. */
  readonly suggestion: CopilotSuggestion;
  readonly problem: (
    status: number,
    code: string,
    reason: string | undefined,
    detail: string,
  ) => void;
  readonly forbidden: () => void;
}

interface Turn {
  message_id: string;
  role: "user" | "assistant";
  text: string;
  status: "answered" | "abstain" | "denied" | "error" | null;
  reason_code: string | null;
  citations: Record<string, unknown>[];
  created_at: string;
  retention_class: string;
  expires_at: string;
}

interface Conversation {
  id: string;
  created_at: string;
  updated_at: string;
  retention_class: string;
  expires_at: string;
  turns: Turn[];
}

interface ReportDoc {
  id: string;
  domain_id: string;
  owner: string;
  title: string;
  chart_plan: Record<string, unknown>;
  query_spec: Record<string, unknown>;
  metric: string;
  shares: string[];
  publication: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  etag: string;
  is_owner: boolean;
  can_decide_publication: boolean;
}

export interface CopilotMockState {
  readonly conversations: Map<string, Conversation>;
  readonly reports: Map<string, ReportDoc>;
  etagCounter: number;
}

// ---- shared fixtures -------------------------------------------------------------------------

const BAR_ROWS = [
  { agent: "support-gpt", cost: 1280.5 },
  { agent: "sales-assist", cost: 940.25 },
  { agent: "hr-helper", cost: 312.0 },
];

/** A valid bar plan (inline data only, no expr/signals/url) that the chart validator accepts. */
export function barPlan(
  rows: readonly Record<string, unknown>[] = BAR_ROWS,
): Record<string, unknown> {
  return {
    schema_version: "1.0.0",
    citations: [{ evidence_id: "ev-mock-cost-1", as_of: NOW }],
    spec: {
      title: "Cost by agent (estimated)",
      data: { values: rows },
      mark: "bar",
      encoding: {
        x: { field: "agent", type: "nominal" },
        y: { field: "cost", type: "quantitative" },
      },
    },
  };
}

function querySpec(): Record<string, unknown> {
  return {
    schema_version: "1.0.0",
    operation: "aggregate",
    entity: "cost_record",
    budget: { timeout_ms: 2000, limit: 20, max_depth: 0 },
    time_bucket: "day",
  };
}

function seedReport(
  id: string,
  domain: string,
  over: Partial<ReportDoc> & { title: string },
): ReportDoc {
  return {
    id,
    domain_id: domain,
    owner: MOCK_OWNER,
    chart_plan: barPlan([{ agent: "sample", cost: 1 }]),
    query_spec: querySpec(),
    metric: "cost",
    shares: [],
    publication: {
      state: "none",
      requested_by: null,
      requested_at: null,
      decided_by: null,
      decided_at: null,
      reason: null,
    },
    created_at: NOW,
    updated_at: NOW,
    etag: `"etag-${id}-1"`,
    is_owner: true,
    can_decide_publication: false,
    ...over,
  };
}

export function freshCopilotState(domain: string, demo = false): CopilotMockState {
  const reports = new Map<string, ReportDoc>();
  const seeds: ReportDoc[] = [
    seedReport(REPORT_SEED_OWN, domain, { title: "Cost by agent" }),
    seedReport(REPORT_SEED_PENDING, domain, {
      title: "Latency review (pending add-to-UI)",
      owner: OTHER_OWNER,
      is_owner: false,
      can_decide_publication: true,
      metric: "latency",
      publication: {
        state: "pending",
        requested_by: OTHER_OWNER,
        requested_at: NOW,
        decided_by: null,
        decided_at: null,
        reason: null,
      },
    }),
    seedReport(REPORT_SEED_APPROVED, domain, {
      title: "Error rate (approved)",
      owner: OTHER_OWNER,
      is_owner: false,
      metric: "errors",
      publication: {
        state: "approved",
        requested_by: OTHER_OWNER,
        requested_at: NOW,
        decided_by: MOCK_OWNER,
        decided_at: NOW,
        reason: null,
      },
    }),
  ];
  if (demo) {
    DEMO_REPORT_TITLES.forEach((extra, i) => {
      seeds.push(
        seedReport(`rpt-demo-${i + 1}`, domain, {
          title: extra.title,
          metric: extra.metric,
        }),
      );
    });
  }
  for (const r of seeds) reports.set(r.id, r);
  return { conversations: new Map(), reports, etagCounter: 1 };
}

// ---- http helpers ----------------------------------------------------------------------------

function json(
  ctx: CopilotMockContext,
  status: number,
  body: unknown,
  extra: Record<string, string> = {},
): void {
  ctx.res.writeHead(status, { "content-type": "application/json", ...ctx.cors, ...extra });
  ctx.res.end(JSON.stringify(body));
}

function noContent(ctx: CopilotMockContext): void {
  ctx.res.writeHead(204, ctx.cors);
  ctx.res.end();
}

function parse(raw: string): Record<string, unknown> | undefined {
  try {
    const parsed: unknown = JSON.parse(raw);
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : undefined;
  } catch {
    return undefined;
  }
}

function admit(ctx: CopilotMockContext): boolean {
  if (!ctx.authorized) {
    json(ctx, 401, { error: "missing or unrecognised token" });
    return false;
  }
  return true;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ---- copilot ---------------------------------------------------------------------------------

function sse(res: ServerResponse, name: string, data: unknown): void {
  res.write(`event: ${name}\ndata: ${JSON.stringify(data)}\n\n`);
}

/** Fixture from the `fixture` query parameter, `fixture:<name>` in the text, or a keyword. */
export function selectFixture(text: string, param: string | null): FixtureName {
  const isName = (v: string): v is FixtureName => (FIXTURE_NAMES as readonly string[]).includes(v);
  if (param !== null && isName(param)) return param;
  const lowered = text.toLowerCase();
  const tagged = /fixture:([a-z_]+)/.exec(lowered)?.[1];
  if (tagged !== undefined && isName(tagged)) return tagged;
  if (lowered.includes("abstain")) return "abstain";
  if (lowered.includes("denied") || lowered.includes("deny")) return "denied";
  if (lowered.includes("swap") || lowered.includes("action")) return "action_suggestion";
  if (lowered.includes("error")) return "error";
  return "answered";
}

function contextEvent(body: Record<string, unknown> | undefined, domain: string): unknown {
  const raw = body?.["context"];
  const c = typeof raw === "object" && raw !== null ? (raw as Record<string, unknown>) : {};
  const selection = Array.isArray(c["selection"]) ? c["selection"] : [];
  return {
    page: typeof c["page"] === "string" ? c["page"] : null,
    route: typeof c["route"] === "string" ? c["route"] : null,
    filters: typeof c["filters"] === "object" && c["filters"] !== null ? c["filters"] : {},
    time_range: typeof c["time_range"] === "object" ? c["time_range"] : null,
    selection,
    dropped_selection_count: 0,
    applied_domains: [typeof c["domain_id"] === "string" ? c["domain_id"] : domain],
  };
}

const ANSWER_TOKENS = [
  "Spend on ",
  "support-gpt is the highest this week ",
  "[cite:r1]. ",
  "Sales-assist trails it ",
  "[cite:r2], ",
  "and the HR helper figure is not confirmed ",
  "[cite:r3].",
];

async function streamFixture(
  ctx: CopilotMockContext,
  conversation: Conversation,
  fixture: FixtureName,
  text: string,
  body: Record<string, unknown> | undefined,
): Promise<void> {
  const { res } = ctx;
  const messageId = randomUUID();
  res.writeHead(200, {
    "content-type": "text/event-stream",
    "cache-control": "no-cache, no-transform",
    connection: "keep-alive",
    "x-accel-buffering": "no",
    ...ctx.cors,
  });
  res.flushHeaders();
  ctx.req.socket.setNoDelay(true);
  sse(res, "context", contextEvent(body, ctx.readableDomains[0] ?? ""));

  const turn = (status: Turn["status"], reason: string | null, reply: string): void => {
    const at = new Date().toISOString();
    conversation.turns.push(
      {
        message_id: randomUUID(),
        role: "user",
        text,
        status: null,
        reason_code: null,
        citations: [],
        created_at: at,
        retention_class: conversation.retention_class,
        expires_at: conversation.expires_at,
      },
      {
        message_id: messageId,
        role: "assistant",
        text: status === "answered" ? reply : "",
        status,
        reason_code: reason,
        citations: [],
        created_at: at,
        retention_class: conversation.retention_class,
        expires_at: conversation.expires_at,
      },
    );
    conversation.updated_at = at;
  };

  if (fixture === "error") {
    sse(res, "tool", { name: "search_catalog", status: "started" });
    sse(res, "error", {
      code: "dependency_transient",
      detail: "The model endpoint is unavailable.",
    });
    res.end();
    return;
  }
  if (fixture === "denied") {
    sse(res, "tool", { name: "export_data", status: "refused" });
    sse(res, "denied", {
      message_id: messageId,
      reason_code: "tool_not_registered",
      reason: "That request needs a tool the copilot is not allowed to use.",
    });
    turn("denied", "tool_not_registered", "");
    res.end();
    return;
  }
  if (fixture === "abstain") {
    sse(res, "tool", { name: "search_catalog", status: "started" });
    sse(res, "tool", { name: "search_catalog", status: "ok" });
    // Tokens streamed before an abstain are discarded by the UI and never persisted as an answer.
    sse(res, "token", { text: "I could not find " });
    await sleep(TOKEN_PACE_MS);
    sse(res, "abstain", {
      message_id: messageId,
      reason_code: "no_authorized_evidence",
      reason: "No records you are allowed to read support an answer.",
    });
    turn("abstain", "no_authorized_evidence", "");
    res.end();
    return;
  }
  if (fixture === "action_suggestion") {
    sse(res, "tool", { name: "propose_action", status: "started" });
    sse(res, "tool", { name: "propose_action", status: "ok" });
    const parts = ["A cheaper deployment ", "is available. ", "Review the draft below."];
    for (const [i, part] of parts.entries()) {
      if (i > 0) await sleep(TOKEN_PACE_MS);
      sse(res, "token", { text: part });
    }
    sse(res, "action_suggestion", ctx.suggestion);
    sse(res, "done", { message_id: messageId, status: "answered" });
    turn("answered", null, parts.join(""));
    res.end();
    return;
  }
  // answered
  sse(res, "tool", { name: "get_cost_summary", status: "started" });
  sse(res, "tool", { name: "get_cost_summary", status: "ok" });
  for (const [i, part] of ANSWER_TOKENS.entries()) {
    if (i > 0) await sleep(TOKEN_PACE_MS);
    sse(res, "token", { text: part });
  }
  const citations = [
    { record_id: "r1", kind: "cost_record", source: "aggregates", as_of: NOW, freshness: "fresh" },
    {
      record_id: "r2",
      kind: "cost_record",
      source: "aggregates",
      as_of: STALE_AS_OF,
      freshness: "stale",
    },
    { record_id: "r3", kind: "cost_record", source: "billing", as_of: null, freshness: "unknown" },
  ];
  for (const c of citations) sse(res, "citation", c);
  sse(res, "chart", { chart_plan: barPlan() });
  sse(res, "done", { message_id: messageId, status: "answered" });
  turn("answered", null, ANSWER_TOKENS.join(""));
  res.end();
}

function summary(c: Conversation): Record<string, unknown> {
  return {
    id: c.id,
    created_at: c.created_at,
    updated_at: c.updated_at,
    retention_class: c.retention_class,
    expires_at: c.expires_at,
  };
}

export function copilotHandler(
  ctx: CopilotMockContext,
  state: CopilotMockState,
  rest: string,
): void {
  if (!admit(ctx)) return;
  const { req } = ctx;
  const match = /^conversations(?:\/([^/]+)(?:\/(messages))?)?\/?$/.exec(rest);
  if (match === null) {
    json(ctx, 404, { error: "not found" });
    return;
  }
  const id = match[1] === undefined ? undefined : decodeURIComponent(match[1]);
  const messages = match[2] !== undefined;
  if (id === undefined) {
    if (req.method === "POST") {
      const at = new Date().toISOString();
      const created: Conversation = {
        id: randomUUID(),
        created_at: at,
        updated_at: at,
        retention_class: "standard",
        expires_at: EXPIRES,
        turns: [],
      };
      state.conversations.set(created.id, created);
      json(ctx, 201, {
        id: created.id,
        created_at: created.created_at,
        retention_class: created.retention_class,
        expires_at: created.expires_at,
      });
      return;
    }
    if (req.method === "GET") {
      json(ctx, 200, { items: [...state.conversations.values()].map(summary), next_cursor: null });
      return;
    }
    json(ctx, 405, { error: "method not allowed" });
    return;
  }
  const conversation = state.conversations.get(id);
  if (conversation === undefined) {
    // Unknown and foreign conversations are indistinguishable: 404, never 403.
    ctx.problem(404, "not_found", undefined, "The conversation does not exist.");
    return;
  }
  if (messages) {
    if (req.method !== "POST") {
      json(ctx, 405, { error: "method not allowed" });
      return;
    }
    void ctx.readBody().then((raw) => {
      const body = parse(raw);
      const text = body?.["text"];
      if (typeof text !== "string" || text.trim() === "") {
        ctx.problem(422, "invalid_schema", undefined, "text is required");
        return;
      }
      const fixture = selectFixture(text, ctx.url.searchParams.get("fixture"));
      return streamFixture(ctx, conversation, fixture, text, body);
    });
    return;
  }
  if (req.method === "GET") {
    json(ctx, 200, { ...summary(conversation), turns: conversation.turns });
    return;
  }
  if (req.method === "DELETE") {
    state.conversations.delete(id);
    noContent(ctx);
    return;
  }
  json(ctx, 405, { error: "method not allowed" });
}

// ---- reports ---------------------------------------------------------------------------------

function nextEtag(state: CopilotMockState, id: string): string {
  state.etagCounter += 1;
  return `"etag-${id}-${state.etagCounter}"`;
}

function resetPublication(): Record<string, unknown> {
  return {
    state: "none",
    requested_by: null,
    requested_at: null,
    decided_by: null,
    decided_at: null,
    reason: null,
  };
}

function view(report: ReportDoc): ReportDoc {
  return { ...report, shares: report.is_owner ? report.shares : [] };
}

function respond(ctx: CopilotMockContext, status: number, report: ReportDoc): void {
  json(ctx, status, view(report), { etag: report.etag });
}

/** Missing If-Match is 422, a stale one 409 `stale_version`. Returns true when it may proceed. */
function checkIfMatch(ctx: CopilotMockContext, report: ReportDoc, required: boolean): boolean {
  const given = ctx.req.headers["if-match"];
  if (given === undefined) {
    if (!required) return true;
    ctx.problem(422, "invalid_schema", "if_match_required", "If-Match is required");
    return false;
  }
  if (given !== report.etag) {
    ctx.problem(409, "stale_version", "etag_mismatch", "The report changed since you loaded it.");
    return false;
  }
  return true;
}

function readBodyFields(body: Record<string, unknown> | undefined):
  | {
      title: string;
      chart_plan: Record<string, unknown>;
      query_spec: Record<string, unknown>;
      metric: string;
    }
  | undefined {
  const title = body?.["title"];
  const plan = body?.["chart_plan"];
  const query = body?.["query_spec"];
  if (typeof title !== "string" || title.trim() === "" || title.length > 200) return undefined;
  if (typeof plan !== "object" || plan === null) return undefined;
  if (typeof query !== "object" || query === null) return undefined;
  const metric = body?.["metric"];
  return {
    title,
    chart_plan: plan as Record<string, unknown>,
    query_spec: query as Record<string, unknown>,
    metric: typeof metric === "string" ? metric : "cost",
  };
}

/** Rows are re-evaluated per viewer on every run; a report the caller does not own sees fewer. */
function runBody(report: ReportDoc): Record<string, unknown> {
  const rows = report.is_owner ? BAR_ROWS : BAR_ROWS.slice(0, 1);
  return {
    report_id: report.id,
    status: "ok",
    chart_plan: barPlan(rows),
    citations: [
      {
        record_id: "r1",
        kind: "cost_record",
        source: "aggregates",
        as_of: NOW,
        freshness: "fresh",
      },
      {
        record_id: "r2",
        kind: "cost_record",
        source: "aggregates",
        as_of: STALE_AS_OF,
        freshness: "stale",
      },
    ],
    truncated: false,
    ran_at: new Date().toISOString(),
    etag: report.etag,
  };
}

export function reportsHandler(
  ctx: CopilotMockContext,
  state: CopilotMockState,
  rest: string,
): void {
  if (!admit(ctx)) return;
  const { req } = ctx;
  const match =
    /^domains\/([^/]+)\/reports(?:\/([^/]+)(?:\/(run|shares|publication)(?:\/([^/]+))?)?)?\/?$/.exec(
      rest,
    );
  if (match === null) {
    json(ctx, 404, { error: "not found" });
    return;
  }
  const domain = decodeURIComponent(match[1] ?? "");
  if (!ctx.readableDomains.includes(domain)) {
    ctx.forbidden();
    return;
  }
  const id = match[2] === undefined ? undefined : decodeURIComponent(match[2]);
  const sub = match[3];
  const tail = match[4] === undefined ? undefined : decodeURIComponent(match[4]);

  if (id === undefined) {
    if (req.method === "POST") {
      void ctx.readBody().then((raw) => {
        const fields = readBodyFields(parse(raw));
        if (fields === undefined) {
          ctx.problem(
            422,
            "invalid_schema",
            undefined,
            "title, chart_plan and query_spec are required",
          );
          return;
        }
        const reportId = `rpt-${randomUUID().slice(0, 8)}`;
        const at = new Date().toISOString();
        const created = seedReport(reportId, domain, {
          ...fields,
          created_at: at,
          updated_at: at,
          etag: nextEtag(state, reportId),
        });
        state.reports.set(reportId, created);
        respond(ctx, 201, created);
      });
      return;
    }
    if (req.method === "GET") {
      const wanted = ctx.url.searchParams.get("publication_state");
      const items = [...state.reports.values()]
        .filter((r) => r.domain_id === domain)
        .filter((r) => wanted === null || r.publication["state"] === wanted)
        .map(view);
      json(ctx, 200, { items, next_cursor: null });
      return;
    }
    json(ctx, 405, { error: "method not allowed" });
    return;
  }

  const report = state.reports.get(id);
  if (report === undefined || report.domain_id !== domain) {
    ctx.problem(404, "not_found", undefined, "The report does not exist.");
    return;
  }

  if (sub === undefined) {
    if (req.method === "GET") {
      respond(ctx, 200, report);
      return;
    }
    if (req.method === "PUT") {
      void ctx.readBody().then((raw) => {
        if (!checkIfMatch(ctx, report, true)) return;
        const fields = readBodyFields(parse(raw));
        if (fields === undefined) {
          ctx.problem(
            422,
            "invalid_schema",
            undefined,
            "title, chart_plan and query_spec are required",
          );
          return;
        }
        // Any change resets the add-to-UI workflow.
        const next: ReportDoc = {
          ...report,
          ...fields,
          publication: resetPublication(),
          can_decide_publication: false,
          updated_at: new Date().toISOString(),
          etag: nextEtag(state, report.id),
        };
        state.reports.set(report.id, next);
        respond(ctx, 200, next);
      });
      return;
    }
    if (req.method === "DELETE") {
      if (!checkIfMatch(ctx, report, true)) return;
      state.reports.delete(report.id);
      noContent(ctx);
      return;
    }
    json(ctx, 405, { error: "method not allowed" });
    return;
  }

  if (sub === "run" && req.method === "POST") {
    json(ctx, 200, runBody(report));
    return;
  }

  if (sub === "shares") {
    if (!report.is_owner) {
      ctx.problem(403, "forbidden", "not_owner", "Only the owner can change sharing.");
      return;
    }
    if (req.method === "POST" && tail === undefined) {
      void ctx.readBody().then((raw) => {
        const principal = parse(raw)?.["principal_id"];
        if (typeof principal !== "string" || principal.length < 3) {
          ctx.problem(422, "invalid_schema", undefined, "principal_id is required");
          return;
        }
        if (!checkIfMatch(ctx, report, false)) return;
        const next: ReportDoc = {
          ...report,
          shares: [...new Set([...report.shares, principal])],
          etag: nextEtag(state, report.id),
        };
        state.reports.set(report.id, next);
        respond(ctx, 200, next);
      });
      return;
    }
    if (req.method === "DELETE" && tail !== undefined) {
      if (!checkIfMatch(ctx, report, false)) return;
      const next: ReportDoc = {
        ...report,
        shares: report.shares.filter((s) => s !== tail),
        etag: nextEtag(state, report.id),
      };
      state.reports.set(report.id, next);
      respond(ctx, 200, next);
      return;
    }
  }

  if (sub === "publication" && req.method === "POST") {
    if (tail === undefined) {
      if (!report.is_owner) {
        ctx.problem(403, "forbidden", "not_owner", "Only the owner can request publication.");
        return;
      }
      if (!checkIfMatch(ctx, report, false)) return;
      const next: ReportDoc = {
        ...report,
        publication: {
          ...resetPublication(),
          state: "pending",
          requested_by: report.owner,
          requested_at: new Date().toISOString(),
        },
        etag: nextEtag(state, report.id),
      };
      state.reports.set(report.id, next);
      respond(ctx, 200, next);
      return;
    }
    if (tail === "decision") {
      void ctx.readBody().then((raw) => {
        const body = parse(raw);
        const decision = body?.["decision"];
        if (decision !== "approve" && decision !== "reject") {
          ctx.problem(422, "invalid_schema", undefined, "decision must be approve or reject");
          return;
        }
        // Decisions always require If-Match: a reviewer must decide on the definition they saw.
        if (!checkIfMatch(ctx, report, true)) return;
        if (report.is_owner) {
          ctx.problem(403, "forbidden", "self_approval", "You cannot decide your own request.");
          return;
        }
        if (report.publication["state"] !== "pending") {
          ctx.problem(409, "stale_version", "state_conflict", "There is no pending request.");
          return;
        }
        const reason = body?.["reason"];
        const next: ReportDoc = {
          ...report,
          can_decide_publication: false,
          publication: {
            ...report.publication,
            state: decision === "approve" ? "approved" : "rejected",
            decided_by: MOCK_OWNER,
            decided_at: new Date().toISOString(),
            reason: typeof reason === "string" && reason !== "" ? reason : null,
          },
          etag: nextEtag(state, report.id),
        };
        state.reports.set(report.id, next);
        respond(ctx, 200, next);
      });
      return;
    }
  }
  json(ctx, 404, { error: "not found" });
}
