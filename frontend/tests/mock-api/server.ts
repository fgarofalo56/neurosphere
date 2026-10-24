/**
 * Tiny Node mock API for Playwright (C10). No network beyond loopback, no
 * credentials: the "token" is an obviously fake string minted by the e2e MSAL
 * stub (tests/e2e-support/stubMsal.ts).
 *
 * It only imitates the authorization *outcome* the real API (PRP-06) owns: a
 * persona workspace answers 200 when the caller's fake token carries the
 * matching role and a 403 ProblemDetails otherwise. The UI never decides.
 *
 * Run directly with Node 24 (native type stripping): node tests/mock-api/server.ts
 */
import { createHash, randomUUID } from "node:crypto";
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { fileURLToPath } from "node:url";
import type { ProblemDetails } from "@neurosphere/contracts";
import {
  COPILOT_PATH,
  REPORTS_PATH,
  copilotHandler,
  freshCopilotState,
  reportsHandler,
  type CopilotMockContext,
} from "./copilot.ts";
import { MCP_ADMIN_PATH, freshMcpAdminState, mcpAdminHandler } from "./mcpAdmin.ts";

export const DEFAULT_PORT = 4010;
export const FAKE_TOKEN_PREFIX = "ns-e2e-fake-token.";
const PERSONAS = ["viewer", "analyst", "steward", "admin", "auditor"] as const;
const WORKSPACE_PATH = /^\/api\/v1\/workspaces\/([^/]+)\/?$/;

export interface MockApiOptions {
  /** Origin of the web app under test; echoed back for CORS. */
  readonly allowedOrigin: string;
  /** Base URL the mock tells the app to use (config.json apiBaseUrl). */
  readonly apiBaseUrl: string;
}

function problem(correlationId: string, instance: string): ProblemDetails {
  return {
    schema_version: "1.0.0",
    type: "https://neurosphere.invalid/problems/forbidden",
    title: "Forbidden",
    status: 403,
    detail: "The caller is not permitted to use this workspace.",
    instance,
    code: "forbidden",
    retryable: false,
    correlation_id: correlationId,
  };
}

/** Role carried by the fake token ("ns-e2e-fake-token.Viewer"), lower-cased, or undefined. */
export function roleFromAuthorization(header: string | undefined): string | undefined {
  if (header === undefined || !header.startsWith("Bearer ")) return undefined;
  const token = header.slice("Bearer ".length).trim();
  if (!token.startsWith(FAKE_TOKEN_PREFIX)) return undefined;
  const role = token.slice(FAKE_TOKEN_PREFIX.length).toLowerCase();
  return role === "" ? undefined : role;
}

/** The runtime config.json the e2e app must receive (apiBaseUrl points at this server). */
export function mockPublicConfig(apiBaseUrl: string): Record<string, string> {
  return {
    cloud: "commercial",
    tenantId: "00000000-0000-0000-0000-000000000000",
    clientId: "00000000-0000-0000-0000-000000000000",
    apiBaseUrl,
    apiScope: "api://neurosphere-e2e/access_as_user",
  };
}

// ---- PRP-28: GET /api/v1/me/domains. The stub caller lists the domains the other fixtures treat
// as readable; DOMAIN_FORBIDDEN is never listed. A token carrying the `nodomain` role (for
// example "ns-e2e-fake-token.NoDomain") holds data.read nowhere and gets 403, like the real API.
export const ME_DOMAINS_PATH = "/api/v1/me/domains";
export const NO_DOMAIN_ROLE = "nodomain";

function meDomainItems(): readonly Record<string, unknown>[] {
  // Declared after the DOMAIN_* constants below it is called at request time only.
  const entry = (
    domain_id: string,
    display_name: string,
    display_name_source: "catalog" | "derived",
  ): Record<string, unknown> => ({
    domain_id,
    display_name,
    display_name_source,
    cloud: "commercial",
    permissions: ["data.read"],
  });
  return [
    entry(DOMAIN_ANALYTICS_DOWN, "Analytics (batch down)", "catalog"),
    entry(DOMAIN_OK, "Finance", "catalog"),
    entry(DOMAIN_VIEWER, "Viewer Only", "derived"),
  ];
}

// ---- PRP-24: GET /api/v1/sandbox/status and /entities. Shapes follow the API models
// (SandboxSummary, EntityPage); every body is marked synthetic and sandbox, like the real API.
export const SANDBOX_STATUS_PATH = "/api/v1/sandbox/status";
export const SANDBOX_ENTITIES_PATH = "/api/v1/sandbox/entities";

const SANDBOX_COUNTS: Readonly<Record<string, number>> = {
  domain: 3,
  owner: 4,
  person: 6,
  model_deployment: 5,
  grounding_source: 2,
  tool: 3,
  agent: 4,
  agent_version: 7,
};
const SANDBOX_RELATIONS = 12;

function sandboxStatusBody(): Record<string, unknown> {
  const total = Object.values(SANDBOX_COUNTS).reduce((a, b) => a + b, 0) + SANDBOX_RELATIONS;
  return {
    environment: "sandbox",
    synthetic: true,
    customer_id: "synthco",
    database: "neurosphere-sandbox",
    counts: SANDBOX_COUNTS,
    relations: SANDBOX_RELATIONS,
    total,
  };
}

function sandboxEntitiesBody(url: URL): Record<string, unknown> {
  const requested = url.searchParams.get("kind") ?? "domain";
  const kind = requested in SANDBOX_COUNTS ? requested : "domain";
  const limit = Math.max(1, Number(url.searchParams.get("limit") ?? 25) || 25);
  const offset = Math.max(0, Number(url.searchParams.get("offset") ?? 0) || 0);
  const count = SANDBOX_COUNTS[kind] ?? 0;
  const items: Record<string, unknown>[] = [];
  for (let i = offset; i < Math.min(count, offset + limit); i += 1) {
    items.push({ id: `synthco-${kind}-${i + 1}`, kind, name: `Synthetic ${kind} ${i + 1}` });
  }
  return {
    environment: "sandbox",
    synthetic: true,
    kind,
    items,
    limit,
    offset,
    next_offset: offset + limit < count ? offset + limit : null,
  };
}

// ---- PRP-14 fixtures: GET /api/v1/dashboards/domains/{domain}/{metric} and
// GET /api/v1/reconciliation/domains/{domain}. Shapes follow the contract (Wire contract plus
// the item 4 per-currency references); the numbers are synthetic. The mock only imitates the
// authorization OUTCOME: a domain the stub caller cannot read answers 403, never an empty 200.
const DASHBOARD_PATH =
  /^\/api\/v1\/dashboards\/domains\/([^/]+)\/(cost|latency|errors|coverage)\/?$/;
const RECONCILIATION_PATH = /^\/api\/v1\/reconciliation\/domains\/([^/]+)\/?$/;

/** Domains the stub caller may read. Any other domain id is forbidden (fail closed). */
export const DOMAIN_OK = "commercial:e2e:sandbox:domain:finance";
/** Readable, but the batch analytics backend is disabled; hot aggregates keep serving. */
export const DOMAIN_ANALYTICS_DOWN = "commercial:e2e:sandbox:domain:analytics-down";
/** Not readable by the stub caller: 403 on every dashboards and reconciliation route. */
export const DOMAIN_FORBIDDEN = "commercial:e2e:sandbox:domain:forbidden";
export const ANALYTICS_DISABLED_REASON =
  "no analytics adapter is available for this cloud and region (capability matrix)";
export const ESTIMATED_PRICE_VERSION = {
  id: "sandbox-prices-2026-10",
  effective_date: "2026-10-01",
};
export const INVOICED_PRICE_VERSION = {
  id: "invoice-prices-2026-09",
  effective_date: "2026-09-01",
};
export const FIXTURE_LAG_SECONDS = 120;
export const FIXTURE_WATERMARK = "2026-10-04T21:17:05Z";

interface FixtureValue {
  value: number | null;
  status: "known" | "unknown";
  complete: boolean;
  price_version: { id: string; effective_date: string } | null;
}

const UNKNOWN_VALUE: FixtureValue = {
  value: null,
  status: "unknown",
  complete: false,
  price_version: null,
};

function known(
  value: number,
  complete = true,
  priceVersion: FixtureValue["price_version"] = null,
): FixtureValue {
  return { value, status: "known", complete, price_version: priceVersion };
}

const DAYS = ["2026-10-02T00:00:00Z", "2026-10-03T00:00:00Z", "2026-10-04T00:00:00Z"] as const;

function points(values: readonly FixtureValue[]): { t: string; value: FixtureValue }[] {
  return values.map((value, index) => ({ t: DAYS[index] ?? DAYS[0], value }));
}

function series(
  key: string,
  label: string,
  unit: "currency" | "ms" | "ratio" | "count",
  kind: "estimated" | "invoiced" | null,
  currency: string | null,
  total: FixtureValue,
  values: readonly FixtureValue[],
): Record<string, unknown> {
  return { key, label, kind, unit, currency, total, points: points(values) };
}

function dashboardSeries(metric: string): Record<string, unknown>[] {
  switch (metric) {
    case "cost":
      return [
        // The last day has no known amount: it renders "unknown", never 0, and the total is
        // the partial sum of the known parts with complete=false.
        series(
          "estimated:USD",
          "Cost (estimated, USD)",
          "currency",
          "estimated",
          "USD",
          known(12.5, false, ESTIMATED_PRICE_VERSION),
          [
            known(5, true, ESTIMATED_PRICE_VERSION),
            known(7.5, true, ESTIMATED_PRICE_VERSION),
            { ...UNKNOWN_VALUE },
          ],
        ),
        series(
          "invoiced:USD",
          "Cost (invoiced, USD)",
          "currency",
          "invoiced",
          "USD",
          known(9.25, true, INVOICED_PRICE_VERSION),
          [
            known(4.25, true, INVOICED_PRICE_VERSION),
            known(5, true, INVOICED_PRICE_VERSION),
            known(0, true, INVOICED_PRICE_VERSION),
          ],
        ),
      ];
    case "latency":
      // Percentiles do not combine, so every total is unknown; points may be known.
      return [
        series("p50", "Latency p50", "ms", null, null, { ...UNKNOWN_VALUE }, [
          known(210),
          known(230),
          { ...UNKNOWN_VALUE },
        ]),
        series("p95", "Latency p95", "ms", null, null, { ...UNKNOWN_VALUE }, [
          known(900),
          known(950),
          { ...UNKNOWN_VALUE },
        ]),
        series("p99", "Latency p99", "ms", null, null, { ...UNKNOWN_VALUE }, [
          known(1500),
          known(1600),
          { ...UNKNOWN_VALUE },
        ]),
      ];
    case "errors":
      return [
        series("error_rate", "Error rate", "ratio", null, null, known(0.02, false), [
          known(0.01),
          known(0.03),
          { ...UNKNOWN_VALUE },
        ]),
        series("error_count", "Error count", "count", null, null, known(4, false), [
          known(1),
          known(3),
          { ...UNKNOWN_VALUE },
        ]),
      ];
    default:
      return [
        series("coverage", "Coverage", "ratio", null, null, known(0.75, false), [
          known(1),
          known(0.5),
          known(0.75),
        ]),
      ];
  }
}

function dashboardBody(domain: string, metric: string): Record<string, unknown> {
  const analyticsDown = domain === DOMAIN_ANALYTICS_DOWN;
  return {
    metric,
    domain_id: domain,
    grain: "day",
    window: { start: "2026-10-02T00:00:00Z", end: "2026-10-05T00:00:00Z" },
    freshness: {
      watermark: FIXTURE_WATERMARK,
      lag_seconds: FIXTURE_LAG_SECONDS,
      billing_source_freshness: "2026-10-04T06:00:00Z",
    },
    analytics: analyticsDown
      ? { state: "disabled", reason: ANALYTICS_DISABLED_REASON }
      : { state: "available", reason: null },
    complete: false,
    truncated: false,
    series: dashboardSeries(metric),
    price_versions: metric === "cost" ? [ESTIMATED_PRICE_VERSION, INVOICED_PRICE_VERSION] : [],
  };
}

function reconciliationBody(domain: string): Record<string, unknown> {
  const reference = {
    label: "ledger (one record per request)",
    amount: known(20),
    currency: "USD",
  };
  return {
    domain_id: domain,
    window: { start: "2026-10-02T00:00:00Z", end: "2026-10-05T00:00:00Z" },
    freshness: {
      watermark: FIXTURE_WATERMARK,
      lag_seconds: FIXTURE_LAG_SECONDS,
      billing_source_freshness: "2026-10-04T06:00:00Z",
    },
    complete: false,
    truncated: false,
    reference,
    references: [{ ...reference, entry_count: 12, unknown_entry_count: 3 }],
    sources: [
      {
        source: "gateway",
        granularity: "request",
        amount: known(20),
        coverage: known(0.75, false),
        variance: known(0),
        currency: "USD",
      },
      {
        source: "app",
        granularity: "request",
        amount: known(19.5),
        coverage: known(0.5, false),
        variance: known(-0.5),
        currency: "USD",
      },
      {
        // Vendor-period totals only: no ledger entry was observed by billing, so its coverage is
        // unknown (not 0%), while the vendor-level amount is known.
        source: "billing",
        granularity: "vendor",
        amount: known(18),
        coverage: { ...UNKNOWN_VALUE },
        variance: known(-2),
        currency: "USD",
      },
    ],
    unknown_remainder: { ...known(3), unit: "entries" },
    disclaimer: "not_all_spend_observable",
  };
}

function serveDomainRead(
  res: ServerResponse,
  req: IncomingMessage,
  url: URL,
  domainSegment: string,
  body: (domain: string) => Record<string, unknown>,
  cors: Record<string, string>,
  correlationId: string,
): void {
  if (roleFromAuthorization(req.headers.authorization) === undefined) {
    send(res, 401, { error: "missing or unrecognised token" }, cors);
    return;
  }
  const domain = decodeURIComponent(domainSegment);
  if (domain !== DOMAIN_OK && domain !== DOMAIN_ANALYTICS_DOWN) {
    send(res, 403, problem(correlationId, url.pathname), cors, "application/problem+json");
    return;
  }
  send(res, 200, body(domain), { ...cors, "server-timing": "app;dur=1.0" });
}

// ---- PRP-15 fixtures: /api/v1/recommendations/domains/{domain}[/items/{id}|/review-requests|
// /executions]. Shapes follow the Recommendation schema and item 4's responses. Synthetic data.
// Only DOMAIN_OK is readable; every other domain answers 403 (never an empty 200).
const RECOMMENDATION_BASE = /^\/api\/v1\/recommendations\/domains\/([^/]+)(\/.*)?$/;
const REC_PREFIX = "commercial:e2e:neurosphere:recommendation:";
export const REC_RIGHT_SIZING = `${REC_PREFIX}model-right-sizing-0a1b2c3d4e5f60718293a4b5`;
export const REC_UNUSED = `${REC_PREFIX}unused-agent-1b2c3d4e5f60718293a4b5c6`;
export const REC_COST_SPIKE = `${REC_PREFIX}cost-spike-2c3d4e5f60718293a4b5c6d7`;
export const REC_DUPLICATE = `${REC_PREFIX}candidate-duplicate-3d4e5f60718293a4b5c6d7e8`;
export const RECOMMENDATION_NEXT_CURSOR = "page-2";
export const RECOMMENDATION_REVIEW_ID = "review-e2e-0001";
export const RECOMMENDATION_PRICE_VERSION = "sandbox-prices-2026-10";
const REC_OWNER = "commercial:e2e:entra:owner:team-support";

function recBase(id: string, kind: string): Record<string, unknown> {
  return {
    schema_version: "1.0.0",
    recommendation_id: id,
    cloud: "commercial",
    customer_id: "e2e",
    domain_id: DOMAIN_OK,
    kind,
    subject_ids: ["commercial:e2e:sandbox:agent:support-bot"],
    method: "rule",
    advisory: true,
    created_at: "2026-10-10T06:00:00Z",
  };
}

function recommendationFixtures(): Record<string, Record<string, unknown>> {
  const window = { start: "2026-10-03T00:00:00Z", end: "2026-10-10T00:00:00Z" };
  return {
    [REC_RIGHT_SIZING]: {
      ...recBase(REC_RIGHT_SIZING, "model_right_sizing"),
      subject_ids: [
        "commercial:e2e:sandbox:agent:support-bot",
        "commercial:e2e:sandbox:model_deployment:gpt-large",
      ],
      generator: { generator_id: "rule.right-sizing", generator_version: "1.0.0" },
      evidence_status: "insufficient_evidence",
      evidence_window: window,
      evidence_ids: ["ev:telemetry:tokens"],
      coverage: { method: "partial", observed_fraction: 0.6 },
      uncertainty: { method: "not_estimable" },
      prerequisites: [
        { kind: "quality_regression_test", status: "unmet" },
        { kind: "tool_compatibility", status: "unmet" },
      ],
      projected_estimate: {
        estimate_kind: "estimated",
        period: "monthly",
        baseline_amount: "1840.00",
        projected_amount: "1210.50",
        lower_amount: "1105.00",
        upper_amount: "1390.00",
        currency: "USD",
        price_version: RECOMMENDATION_PRICE_VERSION,
        price_effective_date: "2026-10-01",
      },
      owner: { resolution: "inferred", owner_id: REC_OWNER },
    },
    [REC_UNUSED]: {
      ...recBase(REC_UNUSED, "unused_agent"),
      evidence_status: "insufficient_evidence",
      evidence_window: window,
      evidence_ids: [],
      coverage: { method: "unknown", observed_fraction: null },
      uncertainty: { method: "not_estimable" },
      prerequisites: [],
      owner: { resolution: "unresolved", owner_id: null },
    },
    [REC_COST_SPIKE]: {
      ...recBase(REC_COST_SPIKE, "cost_spike"),
      generator: { generator_id: "cost-spike-ratio", generator_version: "1.0.0" },
      evidence_status: "sufficient",
      score: 0.86,
      evidence_window: window,
      evidence_ids: ["ev:cost:2026-10"],
      coverage: { method: "full", observed_fraction: 0.97 },
      uncertainty: { method: "bootstrap", lower: 0.78, upper: 0.91, level: 0.95 },
      prerequisites: [],
      owner: { resolution: "assigned", owner_id: REC_OWNER },
    },
    [REC_DUPLICATE]: {
      ...recBase(REC_DUPLICATE, "candidate_duplicate"),
      subject_ids: [
        "commercial:e2e:sandbox:agent:support-bot",
        "commercial:e2e:sandbox:agent:support-bot-2",
      ],
      generator: { generator_id: "duplicate-similarity", generator_version: "1.0.0" },
      evidence_status: "sufficient",
      score: 0.93,
      evidence_window: window,
      evidence_ids: ["ev:catalog:shared-sources"],
      coverage: { method: "full", observed_fraction: 1 },
      uncertainty: { method: "not_estimable" },
      prerequisites: [],
      owner: { resolution: "assigned", owner_id: REC_OWNER },
    },
  };
}

function recommendationHandler(
  res: ServerResponse,
  req: IncomingMessage,
  url: URL,
  parts: { domain: string; rest: string },
  state: { routed: Map<string, string> },
  cors: Record<string, string>,
  correlationId: string,
  readBody: () => Promise<string>,
): void {
  if (roleFromAuthorization(req.headers.authorization) === undefined) {
    send(res, 401, { error: "missing or unrecognised token" }, cors);
    return;
  }
  if (parts.domain !== DOMAIN_OK) {
    send(res, 403, problem(correlationId, url.pathname), cors, "application/problem+json");
    return;
  }
  const fixtures = recommendationFixtures();
  const order = [REC_RIGHT_SIZING, REC_UNUSED, REC_COST_SPIKE, REC_DUPLICATE];
  const { rest } = parts;
  if (req.method === "GET" && rest === "") {
    const kind = url.searchParams.get("kind");
    const q = (url.searchParams.get("q") ?? "").toLowerCase();
    const cursor = url.searchParams.get("cursor");
    const matching = order
      .map((id) => fixtures[id] as Record<string, unknown>)
      .filter((r) => kind === null || r["kind"] === kind)
      .filter((r) => q === "" || `${String(r["kind"])} ${String(r["subject_ids"])}`.includes(q));
    // The unfiltered view is split in two pages so the cursor path is exercised.
    const paged = kind === null && q === "";
    const items = !paged
      ? matching
      : cursor === RECOMMENDATION_NEXT_CURSOR
        ? matching.slice(3)
        : matching.slice(0, 3);
    const next = paged && cursor !== RECOMMENDATION_NEXT_CURSOR ? RECOMMENDATION_NEXT_CURSOR : null;
    send(res, 200, { items, next_cursor: next }, { ...cors, "server-timing": "app;dur=1.0" });
    return;
  }
  const detail = /^\/items\/(.+)$/.exec(rest);
  if (req.method === "GET" && detail !== null) {
    const id = decodeURIComponent(detail[1] ?? "");
    const rec = fixtures[id];
    if (rec === undefined) {
      send(res, 404, { detail: "recommendation not found" }, cors);
      return;
    }
    const reviewId = state.routed.get(id);
    send(
      res,
      200,
      {
        recommendation: rec,
        review:
          reviewId === undefined
            ? { state: "not_routed", review_request_id: null }
            : { state: "pending_review", review_request_id: reviewId },
        execution: { executable: false, reason: "action gates not passed" },
      },
      cors,
    );
    return;
  }
  if (req.method === "POST" && rest === "/review-requests") {
    void readBody().then((raw) => {
      let id: string;
      try {
        const parsed = JSON.parse(raw) as { recommendation_id?: unknown };
        id = typeof parsed.recommendation_id === "string" ? parsed.recommendation_id : "";
      } catch {
        id = "";
      }
      if (fixtures[id] === undefined) {
        send(res, 404, { detail: "recommendation not found" }, cors);
        return;
      }
      state.routed.set(id, RECOMMENDATION_REVIEW_ID);
      send(
        res,
        202,
        { review_request_id: RECOMMENDATION_REVIEW_ID, state: "pending_review" },
        cors,
      );
    });
    return;
  }
  if (req.method === "POST" && rest === "/executions") {
    // There is no executing path: the mock mirrors the API's refusal.
    send(
      res,
      409,
      {
        schema_version: "1.0.0",
        type: "https://neurosphere.invalid/problems/capability-unavailable",
        title: "Capability unavailable",
        status: 409,
        detail: "action gates not passed",
        instance: url.pathname,
        code: "capability_unavailable",
        reason: "action_gates_not_passed",
        retryable: false,
        correlation_id: correlationId,
      } satisfies ProblemDetails,
      cors,
      "application/problem+json",
    );
    return;
  }
  send(res, 404, { error: "not found" }, cors);
}

// ---- PRP-16 fixtures: GET /api/v1/evaluation/domains/{domain}/quality. The shape follows the
// item 4 wire contract (`QualityResponse`); the numbers are SYNTHETIC. DOMAIN_OK answers a
// populated response, DOMAIN_NO_PILOT a response with nothing estimable, any other domain 403
// (never an empty 200).
const EVALUATION_QUALITY = /^\/api\/v1\/evaluation\/domains\/([^/]+)\/quality\/?$/;
/** Readable, but no pilot data and no judged items yet: everything is unknown. */
export const DOMAIN_NO_PILOT = "commercial:e2e:sandbox:domain:no-pilot";
export const PILOT_TARGET_LABEL = "pilot-set target: at least 90%";
export const QUALITY_JUDGE_MODEL = "commercial:e2e:foundry:modeldeployment:judge-a";
export const QUALITY_UNCALIBRATED_MODEL = "commercial:e2e:foundry:modeldeployment:judge-b";

const NULL_JUDGE = {
  judge_model_id: null,
  judge_model_version: null,
  judge_prompt_version: null,
  program_version: null,
};

function qualityBody(domain: string): Record<string, unknown> {
  const target = { target: 0.9, target_label: PILOT_TARGET_LABEL };
  if (domain === DOMAIN_NO_PILOT) {
    return {
      trends: [],
      coverage: [],
      missing_labels: { judged: 0, labelled: null, missing: null },
      pilot_grounded_rate: {
        value: null,
        lower: null,
        upper: null,
        level: null,
        n: 0,
        method: "not_estimable",
        ...target,
      },
      drift_alerts: [],
    };
  }
  const llm = {
    judge_kind: "llm_judge",
    judge_model_id: QUALITY_JUDGE_MODEL,
    judge_model_version: "2026-04-14",
    judge_prompt_version: "grounded-v1",
    program_version: null,
  };
  return {
    trends: [
      {
        dimension: "groundedness",
        points: [
          {
            bucket_start: "2026-10-19T00:00:00Z",
            value: 0.875,
            lower: 0.7389,
            upper: 0.9454,
            level: 0.95,
            sample_size: 40,
            judge: llm,
            calibration_state: "calibrated",
          },
          {
            // Online groundedness is not estimable (bodies are not archived): unknown, never 0.
            bucket_start: "2026-10-19T00:00:00Z",
            value: null,
            lower: null,
            upper: null,
            level: null,
            sample_size: 0,
            judge: { ...NULL_JUDGE, judge_kind: "programmatic", program_version: "outcome-1.0.0" },
            calibration_state: "not_applicable",
          },
        ],
      },
      {
        dimension: "tool_correctness",
        points: [
          {
            bucket_start: "2026-10-19T00:00:00Z",
            value: 0.8,
            lower: 0.62,
            upper: 0.91,
            level: 0.95,
            sample_size: 25,
            judge: {
              ...llm,
              judge_model_id: QUALITY_UNCALIBRATED_MODEL,
              judge_prompt_version: "tools-v2",
            },
            calibration_state: "uncalibrated",
          },
        ],
      },
    ],
    coverage: [
      { stratum: "finance/groundedness/public", sampled: 16, population: 16, coverage_fraction: 1 },
      {
        stratum: "finance/groundedness/restricted",
        sampled: 0,
        population: 8,
        coverage_fraction: 0,
      },
      { stratum: "finance/tool/unmapped", sampled: 5, population: null, coverage_fraction: null },
    ],
    missing_labels: { judged: 40, labelled: 34, missing: 6 },
    pilot_grounded_rate: {
      value: 0.875,
      lower: 0.7389,
      upper: 0.9454,
      level: 0.95,
      n: 40,
      method: "wilson_score",
      ...target,
    },
    drift_alerts: [
      {
        dimension: "groundedness",
        subject_id: "commercial:e2e:sandbox:agent:support-bot",
        detected_at: "2026-10-19T12:00:00Z",
        statistic: 0.7297,
        threshold: 0.25,
      },
    ],
  };
}

function qualityHandler(
  res: ServerResponse,
  req: IncomingMessage,
  url: URL,
  domainSegment: string,
  cors: Record<string, string>,
  correlationId: string,
): void {
  if (roleFromAuthorization(req.headers.authorization) === undefined) {
    send(res, 401, { error: "missing or unrecognised token" }, cors);
    return;
  }
  const domain = decodeURIComponent(domainSegment);
  if (domain !== DOMAIN_OK && domain !== DOMAIN_NO_PILOT) {
    send(res, 403, problem(correlationId, url.pathname), cors, "application/problem+json");
    return;
  }
  send(res, 200, qualityBody(domain), { ...cors, "server-timing": "app;dur=1.0" });
}

// ---- PRP-18 fixtures: GET /api/v1/map/domains/{domain}/viewport and
// GET /api/v1/replay/domains/{domain}/traces[/{trace_id}]. Shapes are generated from the shipped
// Python models (map/models.py, replay/models.py), not from memory. DOMAIN_OK and DOMAIN_MAP_PERF
// are readable; every other domain answers 403 (never an empty 200); no token answers 401.
//
// Viewport modes:
//  - no cluster_id: truncated top level (clusters with member_count plus one node of every kind).
//  - cluster_id=<id>: 5 nodes per page, `cursor=page-2` then `cursor=page-3` (last, no next_cursor);
//    page 2 coverage is `delayed`.
//  - perf: DOMAIN_MAP_PERF, or `fixture=perf` on any readable domain. Deterministic
//    min(node_budget, 2000) nodes (default 2000) and min(edge_budget, 5000) edges, never truncated.
const MAP_VIEWPORT = /^\/api\/v1\/map\/domains\/([^/]+)\/viewport\/?$/;
const REPLAY_TRACES = /^\/api\/v1\/replay\/domains\/([^/]+)\/traces\/?$/;
const REPLAY_TRACE = /^\/api\/v1\/replay\/domains\/([^/]+)\/traces\/([^/]+)\/?$/;
/** Readable by the stub caller; serves the deterministic 2000-node viewport by default. */
export const DOMAIN_MAP_PERF = "commercial:e2e:sandbox:domain:map-perf";
export const MAP_CLUSTER_AGENTS = "cluster:agents";
export const MAP_CLUSTER_MODELS = "cluster:models";
export const MAP_NEXT_CURSOR = "page-2";
export const MAP_PERF_NODE_COUNT = 2000;
export const MAP_PERF_MAX_EDGES = 5000;
export const TRACE_COMPLETE = "trace-e2e-complete";
export const TRACE_GAP = "trace-e2e-gap";
export const TRACE_SAMPLED = "trace-e2e-sampled";
export const TRACE_LATE = "trace-e2e-late";
export const TRACE_NEXT_CURSOR = "page-2";
export const TRACE_UNKNOWN_ID = "trace-e2e-unknown";

const MAP_AS_OF = "2026-10-20T10:00:00Z";
const MAP_NODE_KINDS = ["agent", "sub_agent", "model", "source", "person"] as const;
const MAP_HEALTH = ["ok", "degraded", "failing", "unknown"] as const;
const MAP_PROVENANCE = ["observed", "declared", "inferred"] as const;

interface MapMetrics {
  tokens: number | null;
  context_size: number | null;
  frequency: number | null;
  latency_p95_ms: number | null;
  health: (typeof MAP_HEALTH)[number];
}

const NULL_MAP_METRICS: MapMetrics = {
  tokens: null,
  context_size: null,
  frequency: null,
  latency_p95_ms: null,
  health: "unknown",
};

function mapNode(
  id: string,
  kind: string,
  label: string,
  over: { cluster_id?: string | null; member_count?: number | null; metrics?: MapMetrics } = {},
): Record<string, unknown> {
  return {
    id,
    kind,
    label,
    cluster_id: over.cluster_id ?? null,
    member_count: over.member_count ?? null,
    metrics: over.metrics ?? NULL_MAP_METRICS,
  };
}

function mapEdge(
  id: string,
  source: string,
  target: string,
  provenance: (typeof MAP_PROVENANCE)[number],
): Record<string, unknown> {
  return {
    id,
    source,
    target,
    provenance,
    last_observed_at: provenance === "observed" ? MAP_AS_OF : null,
  };
}

function viewportResponse(
  domain: string,
  parts: {
    nodes: Record<string, unknown>[];
    edges: Record<string, unknown>[];
    truncated: boolean;
    truncation_reason?: string | null;
    next_cursor?: string | null;
    coverage: { state: string; lag_seconds: number | null; as_of: string | null };
  },
): Record<string, unknown> {
  return {
    domain_id: domain,
    nodes: parts.nodes,
    edges: parts.edges,
    truncated: parts.truncated,
    truncation_reason: parts.truncation_reason ?? null,
    next_cursor: parts.next_cursor ?? null,
    coverage: parts.coverage,
  };
}

function intParam(url: URL, name: string, fallback: number, max: number): number {
  const raw = Number(url.searchParams.get(name));
  return Number.isInteger(raw) && raw >= 1 ? Math.min(raw, max) : fallback;
}

function perfViewport(domain: string, url: URL): Record<string, unknown> {
  const nodeCount = intParam(url, "node_budget", MAP_PERF_NODE_COUNT, MAP_PERF_NODE_COUNT);
  const edgeCount = Math.min(
    intParam(url, "edge_budget", MAP_PERF_MAX_EDGES, MAP_PERF_MAX_EDGES),
    nodeCount * 2,
  );
  const nodes: Record<string, unknown>[] = [];
  for (let i = 0; i < nodeCount; i += 1) {
    const kind = MAP_NODE_KINDS[i % MAP_NODE_KINDS.length] ?? "agent";
    const metrics: MapMetrics =
      i % 7 === 0
        ? NULL_MAP_METRICS
        : {
            tokens: 1000 + (i % 97) * 10,
            context_size: 4096,
            frequency: (i % 13) + 0.5,
            latency_p95_ms: 100 + (i % 50) * 5,
            health: MAP_HEALTH[i % MAP_HEALTH.length] ?? "unknown",
          };
    nodes.push(
      mapNode(
        `perf:node:${i}`,
        kind,
        kind === "person" ? `Person-${(i % 9973).toString(16).padStart(4, "0")}` : `${kind}-${i}`,
        { metrics },
      ),
    );
  }
  const edges: Record<string, unknown>[] = [];
  for (let i = 0; i < edgeCount; i += 1) {
    const source = i % nodeCount;
    const target = (i * 7 + 1) % nodeCount;
    edges.push(
      mapEdge(
        `perf:edge:${i}`,
        `perf:node:${source}`,
        `perf:node:${target === source ? (target + 1) % nodeCount : target}`,
        MAP_PROVENANCE[i % MAP_PROVENANCE.length] ?? "observed",
      ),
    );
  }
  return viewportResponse(domain, {
    nodes,
    edges,
    truncated: false,
    coverage: { state: "complete", lag_seconds: 0, as_of: MAP_AS_OF },
  });
}

function topLevelViewport(domain: string): Record<string, unknown> {
  const healthy: MapMetrics = {
    tokens: 52000,
    context_size: 8192,
    frequency: 4.5,
    latency_p95_ms: 820,
    health: "ok",
  };
  const nodes = [
    mapNode(MAP_CLUSTER_AGENTS, "cluster", "Agents", { member_count: 120 }),
    mapNode(MAP_CLUSTER_MODELS, "cluster", "Models", { member_count: 14 }),
    mapNode("e2e:agent:support", "agent", "support-agent", { metrics: healthy }),
    mapNode("e2e:sub_agent:triage", "sub_agent", "triage-sub-agent", {
      metrics: { ...healthy, health: "degraded", latency_p95_ms: 2400 },
    }),
    mapNode("e2e:model:gpt", "model", "support-gpt"),
    mapNode("e2e:source:kb", "source", "knowledge-base"),
    mapNode("e2e:person:1", "person", "Person-3fa9"),
  ];
  const edges = [
    mapEdge("e2e:edge:1", "e2e:person:1", "e2e:agent:support", "observed"),
    mapEdge("e2e:edge:2", "e2e:agent:support", "e2e:sub_agent:triage", "declared"),
    mapEdge("e2e:edge:3", "e2e:sub_agent:triage", "e2e:model:gpt", "inferred"),
    mapEdge("e2e:edge:4", "e2e:agent:support", "e2e:source:kb", "observed"),
  ];
  return viewportResponse(domain, {
    nodes,
    edges,
    truncated: true,
    truncation_reason: "node_budget",
    coverage: { state: "partial", lag_seconds: 45, as_of: MAP_AS_OF },
  });
}

function clusterViewport(
  domain: string,
  clusterId: string,
  cursor: string,
): Record<string, unknown> {
  const page = cursor === "page-3" ? 3 : cursor === MAP_NEXT_CURSOR ? 2 : 1;
  const kind = clusterId === MAP_CLUSTER_MODELS ? "model" : "agent";
  const nodes: Record<string, unknown>[] = [];
  for (let i = 0; i < 5; i += 1) {
    const n = (page - 1) * 5 + i;
    nodes.push(
      mapNode(`${clusterId}:member:${n}`, kind, `${kind}-${n}`, {
        cluster_id: clusterId,
        metrics:
          n % 4 === 0
            ? NULL_MAP_METRICS
            : {
                tokens: 900 + n,
                context_size: 4096,
                frequency: 2,
                latency_p95_ms: 300 + n,
                health: "ok",
              },
      }),
    );
  }
  const edges: Record<string, unknown>[] = [];
  for (let i = 1; i < nodes.length; i += 1) {
    edges.push(
      mapEdge(
        `${clusterId}:edge:${page}:${i}`,
        `${clusterId}:member:${(page - 1) * 5}`,
        `${clusterId}:member:${(page - 1) * 5 + i}`,
        MAP_PROVENANCE[i % MAP_PROVENANCE.length] ?? "observed",
      ),
    );
  }
  const last = page === 3;
  return viewportResponse(domain, {
    nodes,
    edges,
    truncated: !last,
    truncation_reason: last ? null : "node_budget",
    next_cursor: last ? null : page === 1 ? MAP_NEXT_CURSOR : "page-3",
    coverage:
      page === 2
        ? { state: "delayed", lag_seconds: 300, as_of: MAP_AS_OF }
        : { state: "complete", lag_seconds: 0, as_of: MAP_AS_OF },
  });
}

function viewportBody(domain: string, url: URL): Record<string, unknown> {
  if (domain === DOMAIN_MAP_PERF || url.searchParams.get("fixture") === "perf") {
    return perfViewport(domain, url);
  }
  const clusterId = url.searchParams.get("cluster_id");
  if (clusterId !== null && clusterId !== "") {
    return clusterViewport(domain, clusterId, url.searchParams.get("cursor") ?? "");
  }
  return topLevelViewport(domain);
}

function admitReadDomain(
  res: ServerResponse,
  req: IncomingMessage,
  url: URL,
  domainSegment: string,
  cors: Record<string, string>,
  correlationId: string,
): string | undefined {
  if (roleFromAuthorization(req.headers.authorization) === undefined) {
    send(res, 401, { error: "missing or unrecognised token" }, cors);
    return undefined;
  }
  const domain = decodeURIComponent(domainSegment);
  if (domain !== DOMAIN_OK && domain !== DOMAIN_MAP_PERF) {
    send(res, 403, problem(correlationId, url.pathname), cors, "application/problem+json");
    return undefined;
  }
  return domain;
}

function replaySpan(
  id: string,
  parent: string | null,
  name: string,
  kind: string,
  startSecond: number,
  durationMs: number | null,
  over: Record<string, unknown> = {},
): Record<string, unknown> {
  const started = new Date(Date.parse("2026-10-20T10:00:00Z") + startSecond * 1000);
  const iso = (d: Date): string => d.toISOString().replace(".000Z", "Z");
  return {
    span_id: id,
    parent_span_id: parent,
    name,
    kind,
    started_at: iso(started),
    ended_at: durationMs === null ? null : iso(new Date(started.getTime() + durationMs)),
    duration_ms: durationMs,
    status: "ok",
    error: null,
    tool: null,
    agent: null,
    late: false,
    late_reason: null,
    sampled: false,
    sampling_rate: null,
    payload_state: "absent",
    payload: null,
    ...over,
  };
}

function traceCompleteness(
  state: string,
  spanCount: number,
  gapCount: number,
  lateCount: number,
): Record<string, unknown> {
  return {
    state,
    span_count: spanCount,
    gap_count: gapCount,
    late_count: lateCount,
    withheld_span_count: 0,
    truncated: false,
  };
}

function traceDetail(traceId: string): Record<string, unknown> | undefined {
  const root = replaySpan("s1", null, "support-agent", "agent", 0, 2400, {
    agent: "support-agent",
  });
  const model = replaySpan("s2", "s1", "support-gpt", "model", 0.2, 1200, {
    payload_state: "redacted",
  });
  const tool = replaySpan("s3", "s1", "lookup-order", "tool", 1.5, 700, {
    tool: { name: null, outcome: "success" },
  });
  switch (traceId) {
    case TRACE_COMPLETE:
      return {
        trace_id: traceId,
        spans: [root, model, tool],
        gaps: [],
        sampling: { rate: 1, reason: null },
        completeness: traceCompleteness("complete", 3, 0, 0),
      };
    case TRACE_GAP:
      return {
        trace_id: traceId,
        spans: [
          root,
          replaySpan("s4", "s-missing", "orphan-tool", "tool", 1.8, 300, {
            status: "error",
            error: "timeout",
            tool: { name: null, outcome: "timeout" },
          }),
        ],
        gaps: [
          {
            parent_span_id: "s-missing",
            reason: "missing_parent",
            span_id: "s4",
            count: 1,
            detail: "Parent span was never received.",
          },
        ],
        sampling: { rate: 1, reason: null },
        completeness: traceCompleteness("partial", 2, 1, 0),
      };
    case TRACE_SAMPLED:
      return {
        trace_id: traceId,
        spans: [
          { ...root, sampled: true, sampling_rate: 0.25 },
          { ...model, sampled: true, sampling_rate: 0.25 },
        ],
        gaps: [
          {
            parent_span_id: "s1",
            reason: "sampled_out",
            span_id: null,
            count: 3,
            detail: "Child spans were dropped by sampling.",
          },
        ],
        sampling: { rate: 0.25, reason: "head_based" },
        completeness: traceCompleteness("partial", 2, 1, 0),
      };
    case TRACE_LATE:
      return {
        trace_id: traceId,
        spans: [
          root,
          replaySpan("s5", "s1", "late-retrieval", "retrieval", 2, null, {
            late: true,
            late_reason: "arrived_after_root_closed",
            payload_state: "pending",
          }),
        ],
        gaps: [
          {
            parent_span_id: "s1",
            reason: "late_arrival",
            span_id: "s5",
            count: 1,
            detail: "Span arrived after the trace was assembled.",
          },
        ],
        sampling: { rate: 1, reason: null },
        completeness: traceCompleteness("partial", 2, 1, 1),
      };
    default:
      return undefined;
  }
}

function replayList(cursor: string): Record<string, unknown> {
  if (cursor === TRACE_NEXT_CURSOR) {
    return {
      items: [
        {
          trace_id: TRACE_LATE,
          started_at: "2026-10-20T09:00:00Z",
          span_count: 2,
          error_count: 0,
          sampling_rate: 1,
          root_name: "support-agent",
        },
      ],
      next_cursor: null,
    };
  }
  return {
    items: [
      {
        trace_id: TRACE_COMPLETE,
        started_at: "2026-10-20T10:00:00Z",
        span_count: 3,
        error_count: 0,
        sampling_rate: 1,
        root_name: "support-agent",
      },
      {
        trace_id: TRACE_GAP,
        started_at: "2026-10-20T09:50:00Z",
        span_count: 2,
        error_count: 1,
        sampling_rate: 1,
        root_name: "support-agent",
      },
      {
        trace_id: TRACE_SAMPLED,
        started_at: "2026-10-20T09:40:00Z",
        span_count: 2,
        error_count: 0,
        sampling_rate: 0.25,
        root_name: null,
      },
    ],
    next_cursor: TRACE_NEXT_CURSOR,
  };
}

/** Serves the map viewport and replay routes; returns false when the path is not one of them. */
function mapReplayHandler(
  res: ServerResponse,
  req: IncomingMessage,
  url: URL,
  cors: Record<string, string>,
  correlationId: string,
): boolean {
  const viewport = MAP_VIEWPORT.exec(url.pathname);
  const detail = REPLAY_TRACE.exec(url.pathname);
  const list = REPLAY_TRACES.exec(url.pathname);
  const segment = viewport?.[1] ?? detail?.[1] ?? list?.[1];
  if (segment === undefined) return false;
  const domain = admitReadDomain(res, req, url, segment, cors, correlationId);
  if (domain === undefined) return true;
  const headers = { ...cors, "server-timing": "app;dur=1.0" };
  if (viewport !== null) {
    send(res, 200, viewportBody(domain, url), headers);
  } else if (detail !== null) {
    const body = traceDetail(decodeURIComponent(detail[2] ?? ""));
    if (body === undefined) send(res, 404, { error: "trace not found" }, cors);
    else send(res, 200, body, headers);
  } else {
    send(res, 200, replayList(url.searchParams.get("cursor") ?? ""), headers);
  }
  return true;
}

// ---- PRP-17 fixtures: /api/v1/actions/** and /api/v1/review/**. Shapes follow the item 4 wire
// models (ActionView, ReviewItemView, ApprovalDecision); every identity and number is SYNTHETIC.
// The mock imitates only the OUTCOMES the real API owns: DOMAIN_OK allows every call, DOMAIN_VIEWER
// can read but every write answers a 403 problem+json (the Viewer persona), any other domain is
// 403 on every call (never an empty 200). The stub sign-in is always a Viewer token, so the
// persona is selected by the addressed domain rather than by the token.
const ACTIONS_PATH = /^\/api\/v1\/actions\/(.*)$/;
const REVIEW_PATH = /^\/api\/v1\/review\/(.*)$/;
const E2E_PATH = /^\/__e2e\/(.*)$/;
/** Readable, but the caller holds no approver permission: every write is a 403 problem+json. */
export const DOMAIN_VIEWER = "commercial:e2e:sandbox:domain:viewer-only";
const ACTION_TARGET = "commercial:e2e:foundry:model_deployment:support-gpt";
const PAST = "2026-10-01T00:00:00Z";
const RECENT = "2026-10-20T10:00:00Z";
export const INTENT_FLOW = "aaaaaaaa-0000-4000-8000-000000000001";
export const INTENT_ADVISORY = "aaaaaaaa-0000-4000-8000-000000000002";
export const INTENT_EXPIRED = "aaaaaaaa-0000-4000-8000-000000000003";
export const INTENT_STALE = "aaaaaaaa-0000-4000-8000-000000000004";
export const INTENT_REVIEW = "aaaaaaaa-0000-4000-8000-000000000005";
export const INTENT_VIEWER = "aaaaaaaa-0000-4000-8000-000000000006";
export const ITEM_MAKER_CHECKER = "bbbbbbbb-0000-4000-8000-000000000001";
export const ITEM_SUPERSEDED = "bbbbbbbb-0000-4000-8000-000000000002";
export const ITEM_INSIGHT = "bbbbbbbb-0000-4000-8000-000000000003";
export const ITEM_VIEWER = "bbbbbbbb-0000-4000-8000-000000000004";

interface MockPrincipal {
  principal_pseudonym: string;
  principal_kind: string;
  on_behalf_of: string | null;
}

interface MockIntent {
  schema_version: string;
  intent_id: string;
  action_kind: string;
  actor: MockPrincipal;
  target: { canonical_id: string; entity_type: string };
  target_version: string;
  proposed_diff: { format: string; operations: Record<string, unknown>[] };
  prerequisite_results: unknown[];
  evidence: unknown[];
  confirmation_hash: string | null;
  confirmation_expires_at: string | null;
  idempotency_key: string;
  channel: string;
  state: string;
  status_reason: string | null;
  dry_run: boolean;
  correlation_id: string;
  created_at: string;
  state_changed_at: string;
}

interface MockActionView {
  intent: MockIntent;
  advisory: boolean;
  requires_approval: boolean;
  self_approval_forbidden: boolean;
  review_item_id: string | null;
  execution: unknown;
}

interface MockDecision {
  schema_version: string;
  decision_id: string;
  review_item_id: string;
  review_kind: string;
  intent_id: string | null;
  approved_confirmation_hash: string | null;
  reviewer: MockPrincipal;
  maker: MockPrincipal;
  self_approval_allowed: boolean;
  decision: string;
  reason: string;
  policy_version: string;
  decided_at: string;
  correlation_id: string;
}

interface MockReviewItem {
  item_id: string;
  kind: string;
  state: string;
  domain_id: string;
  subject_ref: string;
  intent_id: string | null;
  assignee_pseudonym: string | null;
  sla_due_at: string;
  escalation_level: number;
  created_at: string;
  decisions: MockDecision[];
  effective_decision_id: string | null;
  superseded_decision_ids: string[];
}

interface ActionsState {
  intents: Map<string, { domain: string; view: MockActionView }>;
  items: Map<string, { domain: string; item: MockReviewItem }>;
  drafts: Map<string, string>;
  stale: Set<string>;
}

const MAKER: MockPrincipal = {
  principal_pseudonym: "p-maker",
  principal_kind: "user",
  on_behalf_of: null,
};

function operations(): Record<string, unknown>[] {
  return [
    { op: "replace", path: "/properties/model/name", value: "gpt-4.1-mini" },
    { op: "replace", path: "/properties/model/version", value: "2026-04-14" },
  ];
}

/** Synthetic stand-in for the server's confirmation hash: stable for an exact target+version+diff. */
function confirmationHashFor(intent: MockIntent): string {
  const digest = createHash("sha256")
    .update(JSON.stringify([intent.target, intent.target_version, intent.proposed_diff]))
    .digest("hex");
  return `sha256:${digest}`;
}

function minutesFromNow(minutes: number): string {
  return new Date(Date.now() + minutes * 60_000).toISOString();
}

function makeIntent(id: string, over: Partial<MockIntent> = {}): MockIntent {
  return {
    schema_version: "1.0",
    intent_id: id,
    action_kind: "model_deployment_swap",
    actor: MAKER,
    target: { canonical_id: ACTION_TARGET, entity_type: "model_deployment" },
    target_version: "etag-7",
    proposed_diff: { format: "json_patch", operations: operations() },
    prerequisite_results: [
      {
        check_id: "actor_permission",
        status: "passed",
        detail: null,
        evaluated_at: RECENT,
        evidence_ids: [],
      },
    ],
    evidence: [],
    confirmation_hash: null,
    confirmation_expires_at: null,
    idempotency_key: `seed-${id}`,
    channel: "button",
    state: "drafted",
    status_reason: null,
    dry_run: false,
    correlation_id: `c-${id.slice(-4)}`,
    created_at: RECENT,
    state_changed_at: RECENT,
    ...over,
  };
}

function withConfirmation(intent: MockIntent, expiresAt: string): MockIntent {
  return {
    ...intent,
    state: "awaiting_confirmation",
    confirmation_hash: confirmationHashFor(intent),
    confirmation_expires_at: expiresAt,
  };
}

function makeView(intent: MockIntent, over: Partial<MockActionView> = {}): MockActionView {
  return {
    intent,
    advisory: false,
    requires_approval: true,
    self_approval_forbidden: false,
    review_item_id: null,
    execution: null,
    ...over,
  };
}

function seedIntents(): ActionsState["intents"] {
  const entries: [string, string, MockActionView][] = [
    [INTENT_FLOW, DOMAIN_OK, makeView(makeIntent(INTENT_FLOW))],
    [
      INTENT_ADVISORY,
      DOMAIN_OK,
      makeView(
        makeIntent(INTENT_ADVISORY, {
          action_kind: "agent_instruction_update",
          state: "validated",
        }),
        { advisory: true, requires_approval: false },
      ),
    ],
    [
      INTENT_EXPIRED,
      DOMAIN_OK,
      makeView(withConfirmation(makeIntent(INTENT_EXPIRED, { state: "validated" }), PAST)),
    ],
    [
      INTENT_STALE,
      DOMAIN_OK,
      makeView(
        withConfirmation(makeIntent(INTENT_STALE, { state: "validated" }), minutesFromNow(60)),
      ),
    ],
    [
      INTENT_REVIEW,
      DOMAIN_OK,
      makeView({
        ...withConfirmation(makeIntent(INTENT_REVIEW), minutesFromNow(60)),
        state: "awaiting_approval",
      }),
    ],
    [
      INTENT_VIEWER,
      DOMAIN_VIEWER,
      makeView({
        ...withConfirmation(makeIntent(INTENT_VIEWER), minutesFromNow(60)),
        state: "awaiting_approval",
      }),
    ],
  ];
  return new Map(entries.map(([id, domain, view]) => [id, { domain, view }]));
}

function makeDecision(
  item: { id: string; kind: string; intent: string | null; hash: string | null },
  id: string,
  decision: string,
  reason: string,
): MockDecision {
  return {
    schema_version: "1.0",
    decision_id: id,
    review_item_id: item.id,
    review_kind: item.kind,
    intent_id: item.intent,
    approved_confirmation_hash: item.hash,
    reviewer: {
      principal_pseudonym: `rev-${id.slice(-4)}`,
      principal_kind: "user",
      on_behalf_of: null,
    },
    maker: MAKER,
    self_approval_allowed: false,
    decision,
    reason,
    policy_version: "p-1",
    decided_at: "2026-10-20T11:00:00Z",
    correlation_id: `c-${id.slice(-4)}`,
  };
}

function makeItem(id: string, domain: string, over: Partial<MockReviewItem> = {}): MockReviewItem {
  return {
    item_id: id,
    kind: "maker_checker",
    state: "pending",
    domain_id: domain,
    subject_ref: ACTION_TARGET,
    intent_id: null,
    assignee_pseudonym: null,
    sla_due_at: "2099-01-01T00:00:00Z",
    escalation_level: 0,
    created_at: RECENT,
    decisions: [],
    effective_decision_id: null,
    superseded_decision_ids: [],
    ...over,
  };
}

function seedItems(): ActionsState["items"] {
  const first = "cccccccc-0000-4000-8000-000000000001";
  const second = "cccccccc-0000-4000-8000-000000000002";
  const hash = confirmationHashFor(makeIntent(INTENT_REVIEW));
  const base = { id: ITEM_SUPERSEDED, kind: "maker_checker", intent: INTENT_REVIEW, hash };
  const entries: [string, string, MockReviewItem][] = [
    [
      ITEM_MAKER_CHECKER,
      DOMAIN_OK,
      makeItem(ITEM_MAKER_CHECKER, DOMAIN_OK, { intent_id: INTENT_REVIEW }),
    ],
    [
      ITEM_SUPERSEDED,
      DOMAIN_OK,
      makeItem(ITEM_SUPERSEDED, DOMAIN_OK, {
        state: "approved",
        intent_id: INTENT_REVIEW,
        assignee_pseudonym: "rev-0001",
        // The approval won the race; the later rejection was logged but did not take effect.
        decisions: [
          makeDecision(base, first, "approved", "Diff matches the change request"),
          makeDecision(base, second, "rejected", "Late rejection after the approval landed"),
        ],
        effective_decision_id: first,
        superseded_decision_ids: [second],
      }),
    ],
    [
      ITEM_INSIGHT,
      DOMAIN_OK,
      makeItem(ITEM_INSIGHT, DOMAIN_OK, {
        kind: "recommendation",
        subject_ref: "commercial:e2e:sandbox:agent:support-bot",
      }),
    ],
    [
      ITEM_VIEWER,
      DOMAIN_VIEWER,
      makeItem(ITEM_VIEWER, DOMAIN_VIEWER, { intent_id: INTENT_VIEWER }),
    ],
  ];
  return new Map(entries.map(([id, domain, item]) => [id, { domain, item }]));
}

function freshActionsState(): ActionsState {
  return {
    intents: seedIntents(),
    items: seedItems(),
    drafts: new Map(),
    stale: new Set([INTENT_STALE]),
  };
}

function actionProblem(
  status: number,
  code: ProblemDetails["code"],
  reason: string | undefined,
  detail: string,
  instance: string,
  correlationId: string,
): ProblemDetails {
  return {
    schema_version: "1.0.0",
    type: `https://neurosphere.invalid/problems/${code.replaceAll("_", "-")}`,
    title: code.replaceAll("_", " "),
    status,
    detail,
    instance,
    code,
    ...(reason !== undefined && { reason }),
    retryable: false,
    correlation_id: correlationId,
  } satisfies ProblemDetails;
}

interface ActionsContext {
  res: ServerResponse;
  req: IncomingMessage;
  url: URL;
  cors: Record<string, string>;
  correlationId: string;
  readBody: () => Promise<string>;
  state: ActionsState;
}

function sendProblem(
  ctx: ActionsContext,
  status: number,
  code: ProblemDetails["code"],
  reason: string | undefined,
  detail: string,
): void {
  send(
    ctx.res,
    status,
    actionProblem(status, code, reason, detail, ctx.url.pathname, ctx.correlationId),
    ctx.cors,
    "application/problem+json",
  );
}

function parseJson(raw: string): Record<string, unknown> | undefined {
  try {
    const parsed: unknown = JSON.parse(raw);
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : undefined;
  } catch {
    return undefined;
  }
}

/** Domain gate shared by actions and review: 401 without a token, 403 outside the readable set,
 * and 403 on every write in the viewer-only domain. Returns false when it already answered. */
function admitDomain(ctx: ActionsContext, domain: string, write: boolean): boolean {
  if (roleFromAuthorization(ctx.req.headers.authorization) === undefined) {
    send(ctx.res, 401, { error: "missing or unrecognised token" }, ctx.cors);
    return false;
  }
  if (domain !== DOMAIN_OK && domain !== DOMAIN_VIEWER) {
    send(
      ctx.res,
      403,
      problem(ctx.correlationId, ctx.url.pathname),
      ctx.cors,
      "application/problem+json",
    );
    return false;
  }
  if (write && domain === DOMAIN_VIEWER) {
    sendProblem(
      ctx,
      403,
      "forbidden",
      "permission_denied",
      "The caller does not hold the permission for this action.",
    );
    return false;
  }
  return true;
}

function setIntent(
  state: ActionsState,
  id: string,
  next: (view: MockActionView) => MockActionView,
): MockActionView | undefined {
  const entry = state.intents.get(id);
  if (entry === undefined) return undefined;
  const view = next(entry.view);
  state.intents.set(id, { domain: entry.domain, view });
  return view;
}

function transitionIntent(ctx: ActionsContext, domain: string, id: string, step: string): void {
  const entry = ctx.state.intents.get(id);
  if (entry === undefined || entry.domain !== domain) {
    send(ctx.res, 404, { error: "not found" }, ctx.cors);
    return;
  }
  const { view } = entry;
  const intent = view.intent;
  if (view.advisory) {
    sendProblem(ctx, 400, "capability_unavailable", "advisory_connector", "advisory only");
    return;
  }
  if (step === "validate") {
    if (intent.state !== "drafted") {
      sendProblem(ctx, 409, "stale_version", "state_conflict", "not in the drafted state");
      return;
    }
    const next = setIntent(ctx.state, id, (v) => ({
      ...v,
      intent: { ...v.intent, state: "validated", state_changed_at: RECENT },
    }));
    send(ctx.res, 200, next, ctx.cors);
    return;
  }
  if (step === "confirmation") {
    if (intent.state !== "validated") {
      sendProblem(ctx, 409, "stale_version", "state_conflict", "not in the validated state");
      return;
    }
    const next = setIntent(ctx.state, id, (v) => ({
      ...v,
      intent: withConfirmation(v.intent, minutesFromNow(10)),
    }));
    send(ctx.res, 200, next, ctx.cors);
    return;
  }
  void ctx.readBody().then((raw) => {
    const body = parseJson(raw);
    if (intent.state !== "awaiting_confirmation" && intent.state !== "validated") {
      sendProblem(ctx, 409, "stale_version", "state_conflict", "not awaiting confirmation");
      return;
    }
    if (ctx.state.stale.has(id)) {
      sendProblem(ctx, 409, "stale_version", "target_version_changed", "the target changed");
      return;
    }
    const expires = intent.confirmation_expires_at;
    if (expires === null || Date.parse(expires) <= Date.now()) {
      sendProblem(ctx, 409, "stale_version", "confirmation_expired", "confirmation expired");
      return;
    }
    if (body?.["confirmation_hash"] !== intent.confirmation_hash) {
      sendProblem(ctx, 422, "invalid_schema", "confirmation_hash_mismatch", "hash mismatch");
      return;
    }
    const next = setIntent(ctx.state, id, (v) => ({
      ...v,
      review_item_id: ITEM_MAKER_CHECKER,
      intent: { ...v.intent, state: "awaiting_approval", state_changed_at: RECENT },
    }));
    send(ctx.res, 200, next, ctx.cors);
  });
}

function draftIntent(ctx: ActionsContext, domain: string): void {
  void ctx.readBody().then((raw) => {
    const body = parseJson(raw);
    const target = body?.["target"] as
      { canonical_id?: unknown; entity_type?: unknown } | undefined;
    const diff = body?.["proposed_diff"] as MockIntent["proposed_diff"] | undefined;
    const key = body?.["idempotency_key"];
    if (
      typeof body?.["action_kind"] !== "string" ||
      typeof target?.canonical_id !== "string" ||
      typeof target.entity_type !== "string" ||
      typeof body["target_version"] !== "string" ||
      diff === undefined ||
      typeof key !== "string"
    ) {
      sendProblem(ctx, 422, "invalid_schema", undefined, "invalid draft request");
      return;
    }
    const replay = ctx.state.drafts.get(key);
    const existing = replay === undefined ? undefined : ctx.state.intents.get(replay);
    if (existing !== undefined) {
      send(ctx.res, 200, existing.view, ctx.cors);
      return;
    }
    const id = randomUUID();
    const view = makeView(
      makeIntent(id, {
        action_kind: body["action_kind"],
        target: { canonical_id: target.canonical_id, entity_type: target.entity_type },
        target_version: body["target_version"],
        proposed_diff: diff,
        idempotency_key: key,
        channel: typeof body["channel"] === "string" ? body["channel"] : "button",
      }),
    );
    ctx.state.intents.set(id, { domain, view });
    ctx.state.drafts.set(key, id);
    send(ctx.res, 201, view, ctx.cors);
  });
}

function actionsHandler(ctx: ActionsContext, rest: string): void {
  const { req, state } = ctx;
  if (req.method === "GET" && rest === "emergency-disable") {
    if (roleFromAuthorization(req.headers.authorization) === undefined) {
      send(ctx.res, 401, { error: "missing or unrecognised token" }, ctx.cors);
      return;
    }
    send(
      ctx.res,
      200,
      // Always enabled here: the switch is global, so a spec that needs the disabled banner
      // overrides this one response in its own page instead of flipping shared state.
      { disabled: false, reason: null, changed_by: null, changed_at: null },
      ctx.cors,
    );
    return;
  }
  const match =
    /^domains\/([^/]+)\/intents(?:\/([^/]+)(?:\/(validate|confirmation|confirm))?)?\/?$/.exec(rest);
  if (match === null) {
    send(ctx.res, 404, { error: "not found" }, ctx.cors);
    return;
  }
  const domain = decodeURIComponent(match[1] ?? "");
  const id = match[2] === undefined ? undefined : decodeURIComponent(match[2]);
  const step = match[3];
  const write = req.method === "POST";
  if (!admitDomain(ctx, domain, write)) return;
  if (id === undefined) {
    if (req.method === "POST") {
      draftIntent(ctx, domain);
      return;
    }
    const wanted = ctx.url.searchParams.get("state");
    const items = [...state.intents.values()]
      .filter((e) => e.domain === domain)
      .map((e) => e.view)
      .filter((v) => wanted === null || v.intent.state === wanted);
    send(ctx.res, 200, { items, next_cursor: null }, ctx.cors);
    return;
  }
  if (step !== undefined && req.method === "POST") {
    transitionIntent(ctx, domain, id, step);
    return;
  }
  const entry = state.intents.get(id);
  if (req.method === "GET" && entry !== undefined && entry.domain === domain) {
    send(ctx.res, 200, entry.view, ctx.cors);
    return;
  }
  send(ctx.res, 404, { error: "not found" }, ctx.cors);
}

function reviewDecide(ctx: ActionsContext, domain: string, id: string): void {
  void ctx.readBody().then((raw) => {
    const body = parseJson(raw);
    const entry = ctx.state.items.get(id);
    if (entry === undefined || entry.domain !== domain) {
      send(ctx.res, 404, { error: "not found" }, ctx.cors);
      return;
    }
    const item = entry.item;
    const decision = body?.["decision"];
    const reason = body?.["reason"];
    if (
      (decision !== "approved" && decision !== "rejected") ||
      typeof reason !== "string" ||
      reason.trim() === ""
    ) {
      sendProblem(ctx, 422, "invalid_schema", undefined, "decision and reason are required");
      return;
    }
    if (!["pending", "assigned", "escalated"].includes(item.state)) {
      sendProblem(ctx, 409, "stale_version", "state_conflict", "the item is closed");
      return;
    }
    const intent = item.intent_id === null ? undefined : ctx.state.intents.get(item.intent_id);
    const expected = intent?.view.intent.confirmation_hash ?? null;
    if (item.kind === "maker_checker" && body?.["confirmation_hash"] !== expected) {
      sendProblem(ctx, 422, "invalid_schema", "confirmation_hash_mismatch", "hash mismatch");
      return;
    }
    const decisionId = randomUUID();
    const next: MockReviewItem = {
      ...item,
      state: decision,
      assignee_pseudonym: item.assignee_pseudonym ?? "rev-e2e",
      decisions: [
        ...item.decisions,
        makeDecision(
          { id, kind: item.kind, intent: item.intent_id, hash: expected },
          decisionId,
          decision,
          reason.trim(),
        ),
      ],
      effective_decision_id: decisionId,
    };
    ctx.state.items.set(id, { domain, item: next });
    send(ctx.res, 200, next, ctx.cors);
  });
}

function reviewHandler(ctx: ActionsContext, rest: string): void {
  const { req, state } = ctx;
  const match = /^domains\/([^/]+)\/items(?:\/([^/]+)(?:\/(assignment|decisions))?)?\/?$/.exec(
    rest,
  );
  if (match === null) {
    send(ctx.res, 404, { error: "not found" }, ctx.cors);
    return;
  }
  const domain = decodeURIComponent(match[1] ?? "");
  const id = match[2] === undefined ? undefined : decodeURIComponent(match[2]);
  const action = match[3];
  if (!admitDomain(ctx, domain, req.method === "POST")) return;
  if (id === undefined) {
    const kind = ctx.url.searchParams.get("kind");
    const wanted = ctx.url.searchParams.get("state");
    const items = [...state.items.values()]
      .filter((e) => e.domain === domain)
      .map((e) => e.item)
      .filter((i) => kind === null || i.kind === kind)
      .filter((i) => wanted === null || i.state === wanted);
    send(ctx.res, 200, { items, next_cursor: null }, ctx.cors);
    return;
  }
  const entry = state.items.get(id);
  if (entry === undefined || entry.domain !== domain) {
    send(ctx.res, 404, { error: "not found" }, ctx.cors);
    return;
  }
  if (req.method === "GET" && action === undefined) {
    send(ctx.res, 200, entry.item, ctx.cors);
    return;
  }
  if (req.method === "POST" && action === "assignment") {
    const next = { ...entry.item, state: "assigned", assignee_pseudonym: "rev-e2e" };
    state.items.set(id, { domain, item: next });
    send(ctx.res, 200, next, ctx.cors);
    return;
  }
  if (req.method === "POST" && action === "decisions") {
    reviewDecide(ctx, domain, id);
    return;
  }
  send(ctx.res, 404, { error: "not found" }, ctx.cors);
}

function noContent(ctx: ActionsContext): void {
  ctx.res.writeHead(204, ctx.cors);
  ctx.res.end();
}

/** Test-only controls (loopback mock, never the product API): restore one seeded record. Specs
 * reset the records they mutate so reruns against a reused server and
 * parallel workers stay independent. */
function e2eHandler(ctx: ActionsContext, rest: string): void {
  const reset = /^reset\/([^/]+)$/.exec(rest);
  if (reset !== null) {
    const id = decodeURIComponent(reset[1] ?? "");
    const intent = seedIntents().get(id);
    const item = seedItems().get(id);
    if (intent !== undefined) ctx.state.intents.set(id, intent);
    if (item !== undefined) ctx.state.items.set(id, item);
    if (intent === undefined && item === undefined)
      send(ctx.res, 404, { error: "no seed" }, ctx.cors);
    else noContent(ctx);
    return;
  }
  send(ctx.res, 404, { error: "not found" }, ctx.cors);
}

function send(
  res: ServerResponse,
  status: number,
  body: unknown,
  headers: Record<string, string>,
  contentType = "application/json",
): void {
  res.writeHead(status, { "content-type": contentType, ...headers });
  res.end(JSON.stringify(body));
}

function readRequestBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve) => {
    const chunks: Buffer[] = [];
    req.on("data", (chunk: Buffer) => chunks.push(chunk));
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
  });
}

/** The drafted PRP-17 intent the copilot `action_suggestion` fixture points at (seeded above in
 * DOMAIN_OK, state `drafted`, so the confirmation dialog can load it). Chat never confirms it. */
function copilotSuggestion(): {
  intent_id: string;
  domain_id: string;
  action_type: string;
  target: Record<string, unknown>;
  intent_hash: string;
} {
  const intent = makeIntent(INTENT_FLOW);
  return {
    intent_id: INTENT_FLOW,
    domain_id: DOMAIN_OK,
    action_type: intent.action_kind as string,
    target: intent.target as Record<string, unknown>,
    intent_hash: confirmationHashFor(intent),
  };
}

export function createMockApi(options: MockApiOptions): Server {
  const recommendationState = { routed: new Map<string, string>() };
  const actionsState = freshActionsState();
  const copilotState = freshCopilotState(DOMAIN_OK);
  const mcpAdminState = freshMcpAdminState();
  return createServer((req: IncomingMessage, res: ServerResponse) => {
    const correlationId = `e2e-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    const cors: Record<string, string> = {
      "access-control-allow-origin": options.allowedOrigin,
      "access-control-allow-headers": "authorization, content-type, x-correlation-id, if-match",
      "access-control-allow-methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
      "access-control-expose-headers": "x-correlation-id, retry-after, etag",
      vary: "Origin",
      "x-correlation-id": correlationId,
    };
    const url = new URL(req.url ?? "/", "http://mock.invalid");

    if (req.method === "OPTIONS") {
      res.writeHead(204, cors);
      res.end();
      return;
    }
    const actionsCtx: ActionsContext = {
      res,
      req,
      url,
      cors,
      correlationId,
      readBody: () => readRequestBody(req),
      state: actionsState,
    };
    const actions = ACTIONS_PATH.exec(url.pathname);
    if (actions !== null) {
      actionsHandler(actionsCtx, actions[1] ?? "");
      return;
    }
    const review = REVIEW_PATH.exec(url.pathname);
    if (review !== null) {
      reviewHandler(actionsCtx, review[1] ?? "");
      return;
    }
    const e2e = E2E_PATH.exec(url.pathname);
    if (e2e !== null && req.method === "POST") {
      e2eHandler(actionsCtx, e2e[1] ?? "");
      return;
    }
    const copilotCtx: CopilotMockContext = {
      req,
      res,
      url,
      cors,
      readBody: () => readRequestBody(req),
      authorized: roleFromAuthorization(req.headers.authorization) !== undefined,
      readableDomains: [DOMAIN_OK],
      suggestion: copilotSuggestion(),
      problem: (status, code, reason, detail) =>
        send(
          res,
          status,
          actionProblem(
            status,
            code as ProblemDetails["code"],
            reason,
            detail,
            url.pathname,
            correlationId,
          ),
          cors,
          "application/problem+json",
        ),
      forbidden: () =>
        send(res, 403, problem(correlationId, url.pathname), cors, "application/problem+json"),
    };
    const copilot = COPILOT_PATH.exec(url.pathname);
    if (copilot !== null) {
      copilotHandler(copilotCtx, copilotState, copilot[1] ?? "");
      return;
    }
    const mcpAdmin = MCP_ADMIN_PATH.exec(url.pathname);
    if (mcpAdmin !== null) {
      void mcpAdminHandler(copilotCtx, mcpAdminState, mcpAdmin[1] ?? "");
      return;
    }
    const reports = REPORTS_PATH.exec(url.pathname);
    if (reports !== null) {
      reportsHandler(copilotCtx, copilotState, reports[1] ?? "");
      return;
    }
    const recommendation = RECOMMENDATION_BASE.exec(url.pathname);
    if (recommendation !== null) {
      recommendationHandler(
        res,
        req,
        url,
        { domain: decodeURIComponent(recommendation[1] ?? ""), rest: recommendation[2] ?? "" },
        recommendationState,
        cors,
        correlationId,
        () => readRequestBody(req),
      );
      return;
    }
    if (req.method !== "GET") {
      send(res, 405, { error: "method not allowed" }, cors);
      return;
    }
    if (url.pathname === "/api/v1/health") {
      send(res, 200, { status: "ok" }, cors);
      return;
    }
    if (url.pathname === "/config.json") {
      send(res, 200, mockPublicConfig(options.apiBaseUrl), cors);
      return;
    }
    if (url.pathname === ME_DOMAINS_PATH) {
      const role = roleFromAuthorization(req.headers.authorization);
      if (role === undefined) {
        send(res, 401, { error: "missing or unrecognised token" }, cors);
        return;
      }
      if (role === NO_DOMAIN_ROLE) {
        send(res, 403, problem(correlationId, url.pathname), cors, "application/problem+json");
        return;
      }
      send(res, 200, { items: meDomainItems() }, cors);
      return;
    }
    if (url.pathname === SANDBOX_STATUS_PATH || url.pathname === SANDBOX_ENTITIES_PATH) {
      if (roleFromAuthorization(req.headers.authorization) === undefined) {
        send(res, 401, { error: "missing or unrecognised token" }, cors);
        return;
      }
      send(
        res,
        200,
        url.pathname === SANDBOX_STATUS_PATH ? sandboxStatusBody() : sandboxEntitiesBody(url),
        cors,
      );
      return;
    }
    const dashboard = DASHBOARD_PATH.exec(url.pathname);
    if (dashboard !== null) {
      serveDomainRead(
        res,
        req,
        url,
        dashboard[1] ?? "",
        (domain) => dashboardBody(domain, dashboard[2] ?? "cost"),
        cors,
        correlationId,
      );
      return;
    }
    if (mapReplayHandler(res, req, url, cors, correlationId)) return;
    const quality = EVALUATION_QUALITY.exec(url.pathname);
    if (quality !== null) {
      qualityHandler(res, req, url, quality[1] ?? "", cors, correlationId);
      return;
    }
    const reconciliation = RECONCILIATION_PATH.exec(url.pathname);
    if (reconciliation !== null) {
      serveDomainRead(
        res,
        req,
        url,
        reconciliation[1] ?? "",
        reconciliationBody,
        cors,
        correlationId,
      );
      return;
    }
    const match = WORKSPACE_PATH.exec(url.pathname);
    if (match !== null) {
      const persona = (match[1] ?? "").toLowerCase();
      if (!(PERSONAS as readonly string[]).includes(persona)) {
        send(res, 404, { error: "unknown workspace" }, cors);
        return;
      }
      const role = roleFromAuthorization(req.headers.authorization);
      if (role === undefined) {
        send(res, 401, { error: "missing or unrecognised token" }, cors);
        return;
      }
      if (role !== persona) {
        send(res, 403, problem(correlationId, url.pathname), cors, "application/problem+json");
        return;
      }
      send(res, 200, { workspace: persona, items: [] }, cors);
      return;
    }
    send(res, 404, { error: "not found" }, cors);
  });
}

const isMain = process.argv[1] !== undefined && fileURLToPath(import.meta.url) === process.argv[1];
if (isMain) {
  const port = Number(process.env["NS_MOCK_API_PORT"] ?? DEFAULT_PORT);
  const appOrigin = process.env["NS_E2E_APP_ORIGIN"] ?? "http://127.0.0.1:4173";
  const server = createMockApi({
    allowedOrigin: appOrigin,
    apiBaseUrl: `http://127.0.0.1:${port}`,
  });
  server.listen(port, "127.0.0.1", () => {
    console.log(`mock api listening on http://127.0.0.1:${port}`);
  });
}
