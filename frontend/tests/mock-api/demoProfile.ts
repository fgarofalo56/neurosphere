/**
 * Richer fixtures for the local demo (`NS_MOCK_PROFILE=demo`, started by `pnpm demo`). Test and
 * demo support only: nothing under `tests/` is bundled into the app. The default e2e profile never
 * calls into this file, so the values specs pin stay unchanged.
 *
 * Every number and name is SYNTHETIC. Generation is deterministic (no Math.random, no clock) so a
 * demo and the Playwright demo audit see the same data every time.
 */

export const DEMO_PROFILE = "demo";

const DAY_MS = 86_400_000;
/** Exclusive end of the demo window: the first instant after the last fixture day. */
const DEMO_END = Date.parse("2026-10-26T00:00:00Z");

export const DEMO_FRESHNESS = {
  watermark: "2026-10-25T21:17:05Z",
  lag_seconds: 38,
  billing_source_freshness: "2026-10-25T06:00:00Z",
};

interface PriceVersion {
  id: string;
  effective_date: string;
}

interface DemoValue {
  value: number | null;
  status: "known" | "unknown";
  complete: boolean;
  price_version: PriceVersion | null;
}

function iso(ms: number): string {
  return new Date(ms).toISOString().replace(".000Z", "Z");
}

/** Deterministic wobble in [0, 1): a cheap integer hash, stable across runs. */
function wobble(seed: number): number {
  const x = Math.sin(seed * 12.9898 + 78.233) * 43758.5453;
  return x - Math.floor(x);
}

function knownValue(value: number, priceVersion: PriceVersion | null, complete = true): DemoValue {
  return { value, status: "known", complete, price_version: priceVersion };
}

function unknownValue(): DemoValue {
  return { value: null, status: "unknown", complete: false, price_version: null };
}

interface DemoSeriesSpec {
  readonly key: string;
  readonly label: string;
  readonly unit: "currency" | "ms" | "ratio" | "count";
  readonly kind: "estimated" | "invoiced" | null;
  readonly currency: string | null;
  /** Value of day `i` out of `days` (0 = oldest). */
  readonly at: (i: number, days: number) => number;
  /** Days that carry no known amount (unknown, never 0). */
  readonly unknownDays?: readonly number[];
  /** Days whose value is known but incomplete. */
  readonly incompleteDays?: readonly number[];
  readonly priceVersion?: PriceVersion | null;
  /** Percentiles do not combine, so their total stays unknown. */
  readonly summable: boolean;
  readonly round?: number;
}

function buildSeries(spec: DemoSeriesSpec, days: number): Record<string, unknown> {
  const round = spec.round ?? 2;
  const scale = 10 ** round;
  const unknownDays = new Set((spec.unknownDays ?? []).map((d) => days - 1 - d));
  const incompleteDays = new Set((spec.incompleteDays ?? []).map((d) => days - 1 - d));
  const pv = spec.priceVersion ?? null;
  const points: { t: string; value: DemoValue }[] = [];
  let total = 0;
  let anyIncomplete = false;
  let anyKnown = false;
  for (let i = 0; i < days; i += 1) {
    const t = iso(DEMO_END - (days - i) * DAY_MS);
    if (unknownDays.has(i)) {
      points.push({ t, value: unknownValue() });
      anyIncomplete = true;
      continue;
    }
    const value = Math.round(spec.at(i, days) * scale) / scale;
    const complete = !incompleteDays.has(i);
    if (!complete) anyIncomplete = true;
    anyKnown = true;
    total += value;
    points.push({ t, value: knownValue(value, pv, complete) });
  }
  const totalValue: DemoValue =
    spec.summable && anyKnown
      ? knownValue(Math.round(total * scale) / scale, pv, !anyIncomplete)
      : unknownValue();
  return {
    key: spec.key,
    label: spec.label,
    kind: spec.kind,
    unit: spec.unit,
    currency: spec.currency,
    total: totalValue,
    points,
  };
}

function costSpecs(estimated: PriceVersion, invoiced: PriceVersion): readonly DemoSeriesSpec[] {
  return [
    {
      key: "estimated:USD",
      label: "Cost (estimated, USD)",
      kind: "estimated",
      currency: "USD",
      unit: "currency",
      summable: true,
      priceVersion: estimated,
      at: (i) => 310 + i * 3.2 + wobble(i + 1) * 60,
      unknownDays: [0],
      incompleteDays: [1, 9],
    },
    {
      key: "invoiced:USD",
      label: "Cost (invoiced, USD)",
      kind: "invoiced",
      currency: "USD",
      unit: "currency",
      summable: true,
      priceVersion: invoiced,
      at: (i) => 298 + i * 3 + wobble(i + 40) * 40,
      unknownDays: [0, 1, 2],
    },
    {
      key: "estimated:EUR",
      label: "Cost (estimated, EUR)",
      kind: "estimated",
      currency: "EUR",
      unit: "currency",
      summable: true,
      priceVersion: estimated,
      at: (i) => 120 + i * 1.4 + wobble(i + 80) * 25,
      incompleteDays: [0],
    },
    {
      key: "invoiced:EUR",
      label: "Cost (invoiced, EUR)",
      kind: "invoiced",
      currency: "EUR",
      unit: "currency",
      summable: true,
      priceVersion: invoiced,
      at: (i) => 115 + i * 1.3 + wobble(i + 120) * 18,
      unknownDays: [0, 1],
    },
  ];
}

function otherSpecs(metric: string): readonly DemoSeriesSpec[] {
  switch (metric) {
    case "latency":
      return [
        {
          key: "p50",
          label: "Latency p50",
          kind: null,
          currency: null,
          unit: "ms",
          summable: false,
          round: 0,
          at: (i) => 200 + wobble(i + 3) * 50,
          unknownDays: [0],
        },
        {
          key: "p95",
          label: "Latency p95",
          kind: null,
          currency: null,
          unit: "ms",
          summable: false,
          round: 0,
          at: (i) => 880 + wobble(i + 9) * 160,
          unknownDays: [0],
        },
        {
          key: "p99",
          label: "Latency p99",
          kind: null,
          currency: null,
          unit: "ms",
          summable: false,
          round: 0,
          at: (i) => 1450 + wobble(i + 15) * 320,
          unknownDays: [0],
        },
      ];
    case "errors":
      return [
        {
          key: "error_rate",
          label: "Error rate",
          kind: null,
          currency: null,
          unit: "ratio",
          summable: false,
          round: 4,
          at: (i) => 0.008 + wobble(i + 5) * 0.03,
          unknownDays: [0],
        },
        {
          key: "error_count",
          label: "Error count",
          kind: null,
          currency: null,
          unit: "count",
          summable: true,
          round: 0,
          at: (i) => 2 + Math.floor(wobble(i + 7) * 9),
          unknownDays: [0],
        },
      ];
    default:
      return [
        {
          key: "coverage",
          label: "Coverage",
          kind: null,
          currency: null,
          unit: "ratio",
          summable: false,
          round: 4,
          at: (i, days) => Math.min(1, 0.62 + (i / days) * 0.3 + wobble(i + 11) * 0.06),
          incompleteDays: [0],
        },
      ];
  }
}

/** 30 days (or `days`, 1..90) of daily points ending yesterday, per currency and kind. */
export function demoDashboardSeries(
  metric: string,
  days: number,
  estimated: PriceVersion,
  invoiced: PriceVersion,
): Record<string, unknown>[] {
  const specs = metric === "cost" ? costSpecs(estimated, invoiced) : otherSpecs(metric);
  return specs.map((spec) => buildSeries(spec, days));
}

export function demoWindow(days: number): { start: string; end: string } {
  return { start: iso(DEMO_END - days * DAY_MS), end: iso(DEMO_END) };
}

export function demoDays(raw: string | null): number {
  const n = Number(raw);
  return Number.isInteger(n) && n >= 1 && n <= 90 ? n : 30;
}

// ---- map topology ----------------------------------------------------------------------------

type Health = "ok" | "degraded" | "failing" | "unknown";

export interface DemoMapNode {
  readonly id: string;
  readonly kind: string;
  readonly label: string;
  readonly health: Health;
  readonly tokens: number | null;
  readonly latency: number | null;
}

export interface DemoMapEdge {
  readonly id: string;
  readonly source: string;
  readonly target: string;
  readonly provenance: "observed" | "declared" | "inferred";
}

const AGENTS = [
  "support-agent",
  "sales-assist",
  "hr-helper",
  "finance-copilot",
  "legal-review",
  "it-helpdesk",
] as const;
const SUB_AGENTS = [
  "triage-sub-agent",
  "summarizer",
  "retriever",
  "policy-checker",
  "translator",
  "escalation-router",
] as const;
const MODELS = ["support-gpt", "gpt-large", "gpt-mini", "embedding-v3", "judge-a"] as const;
const SOURCES = [
  "knowledge-base",
  "contracts-index",
  "hr-policies",
  "ticket-history",
  "finance-ledger",
  "product-docs",
] as const;
const PEOPLE = ["Person-3fa9", "Person-71c2", "Person-9d04", "Person-b6e8", "Person-0a5f"] as const;

const HEALTHS: readonly Health[] = ["ok", "ok", "ok", "degraded", "ok", "failing", "ok", "unknown"];

/** A flat, un-truncated, 30-node topology: every kind, every provenance, every health state. */
export function demoTopology(): { nodes: DemoMapNode[]; edges: DemoMapEdge[] } {
  const nodes: DemoMapNode[] = [];
  const add = (prefix: string, kind: string, labels: readonly string[]): void => {
    labels.forEach((label, i) => {
      const n = nodes.length;
      const health = HEALTHS[(n * 3 + i) % HEALTHS.length] ?? "ok";
      const known = health !== "unknown";
      nodes.push({
        id: `demo:${prefix}:${i + 1}`,
        kind,
        label,
        health,
        tokens: known ? 12_000 + Math.floor(wobble(n + 1) * 90_000) : null,
        latency: known ? 240 + Math.floor(wobble(n + 50) * 2400) : null,
      });
    });
  };
  add("agent", "agent", AGENTS);
  add("sub", "sub_agent", SUB_AGENTS);
  add("model", "model", MODELS);
  add("source", "source", SOURCES);
  add("person", "person", PEOPLE);
  const edges: DemoMapEdge[] = [];
  const link = (source: string, target: string, provenance: DemoMapEdge["provenance"]): void => {
    edges.push({ id: `demo:edge:${edges.length + 1}`, source, target, provenance });
  };
  for (let i = 1; i <= AGENTS.length; i += 1) {
    link(`demo:person:${(i % PEOPLE.length) + 1}`, `demo:agent:${i}`, "observed");
    link(`demo:agent:${i}`, `demo:sub:${i}`, "declared");
    link(`demo:agent:${i}`, `demo:source:${i}`, i % 2 === 0 ? "observed" : "inferred");
    link(
      `demo:sub:${i}`,
      `demo:model:${(i % MODELS.length) + 1}`,
      i % 3 === 0 ? "inferred" : "observed",
    );
  }
  link("demo:agent:1", "demo:model:1", "observed");
  link("demo:agent:2", "demo:model:2", "observed");
  link("demo:agent:4", "demo:model:2", "declared");
  link("demo:agent:5", "demo:model:5", "inferred");
  link("demo:sub:3", "demo:source:2", "observed");
  link("demo:sub:4", "demo:source:3", "declared");
  link("demo:person:2", "demo:agent:1", "observed");
  return { nodes, edges };
}

// ---- recommendations -------------------------------------------------------------------------

const REC_PREFIX = "commercial:e2e:neurosphere:recommendation:";
const REC_OWNER = "commercial:e2e:entra:owner:team-support";
const AGENT_PREFIX = "commercial:e2e:sandbox:agent:";

interface DemoRecSpec {
  readonly slug: string;
  readonly kind: string;
  readonly agents: readonly string[];
  readonly score: number | null;
  readonly generator: string;
  readonly estimate?: { baseline: string; projected: string };
}

const DEMO_RECS: readonly DemoRecSpec[] = [
  {
    slug: "unused-agent-d1",
    kind: "unused_agent",
    agents: ["legacy-faq-bot"],
    score: null,
    generator: "rule.unused",
  },
  {
    slug: "cost-spike-d2",
    kind: "cost_spike",
    agents: ["sales-assist"],
    score: 0.91,
    generator: "cost-spike-ratio",
  },
  {
    slug: "cost-spike-d3",
    kind: "cost_spike",
    agents: ["finance-copilot"],
    score: 0.78,
    generator: "cost-spike-ratio",
  },
  {
    slug: "model-right-sizing-d4",
    kind: "model_right_sizing",
    agents: ["hr-helper", "gpt-mini"],
    score: 0.82,
    generator: "rule.right-sizing",
    estimate: { baseline: "920.00", projected: "610.00" },
  },
  {
    slug: "model-right-sizing-d5",
    kind: "model_right_sizing",
    agents: ["it-helpdesk", "gpt-large"],
    score: 0.74,
    generator: "rule.right-sizing",
    estimate: { baseline: "1320.00", projected: "905.00" },
  },
  {
    slug: "candidate-duplicate-d6",
    kind: "candidate_duplicate",
    agents: ["hr-helper", "it-helpdesk"],
    score: 0.88,
    generator: "duplicate-similarity",
  },
  {
    slug: "candidate-duplicate-d7",
    kind: "candidate_duplicate",
    agents: ["legal-review", "policy-checker"],
    score: 0.69,
    generator: "duplicate-similarity",
  },
  {
    slug: "unused-agent-d8",
    kind: "unused_agent",
    agents: ["translator"],
    score: null,
    generator: "rule.unused",
  },
];

function hex24(slug: string): string {
  let h = 0;
  for (const ch of slug) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return h.toString(16).padStart(8, "0").repeat(3);
}

export interface DemoRecommendation {
  readonly id: string;
  readonly record: Record<string, unknown>;
}

/** Extra recommendations on top of the four e2e fixtures (same schema, same owner id). */
export function demoRecommendations(domainId: string): DemoRecommendation[] {
  const window = { start: "2026-10-18T00:00:00Z", end: "2026-10-25T00:00:00Z" };
  return DEMO_RECS.map((spec) => {
    const id = `${REC_PREFIX}${spec.slug}-${hex24(spec.slug)}`;
    const sufficient = spec.score !== null;
    const record: Record<string, unknown> = {
      schema_version: "1.0.0",
      recommendation_id: id,
      cloud: "commercial",
      customer_id: "e2e",
      domain_id: domainId,
      kind: spec.kind,
      subject_ids: spec.agents.map((a) => `${AGENT_PREFIX}${a}`),
      method: "rule",
      advisory: true,
      created_at: "2026-10-25T06:00:00Z",
      generator: { generator_id: spec.generator, generator_version: "1.0.0" },
      evidence_status: sufficient ? "sufficient" : "insufficient_evidence",
      ...(sufficient ? { score: spec.score } : {}),
      evidence_window: window,
      evidence_ids: sufficient ? [`ev:demo:${spec.slug}`] : [],
      coverage: sufficient
        ? { method: "full", observed_fraction: 0.95 }
        : { method: "unknown", observed_fraction: null },
      uncertainty: sufficient
        ? { method: "bootstrap", lower: 0.6, upper: 0.95, level: 0.95 }
        : { method: "not_estimable" },
      prerequisites: [],
      owner: sufficient
        ? { resolution: "assigned", owner_id: REC_OWNER }
        : { resolution: "unresolved", owner_id: null },
      ...(spec.estimate === undefined
        ? {}
        : {
            projected_estimate: {
              estimate_kind: "estimated",
              period: "monthly",
              baseline_amount: spec.estimate.baseline,
              projected_amount: spec.estimate.projected,
              lower_amount: spec.estimate.projected,
              upper_amount: spec.estimate.baseline,
              currency: "USD",
              price_version: "sandbox-prices-2026-10",
              price_effective_date: "2026-10-01",
            },
          }),
    };
    return { id, record };
  });
}

// ---- review items and intents ----------------------------------------------------------------

/** Ids for the extra review items and intents the demo adds (valid v4-shaped UUIDs). */
export function demoIntentId(n: number): string {
  return `aaaaaaaa-0000-4000-8000-0000000001${String(n).padStart(2, "0")}`;
}

export function demoItemId(n: number): string {
  return `bbbbbbbb-0000-4000-8000-0000000001${String(n).padStart(2, "0")}`;
}

export const DEMO_EXTRA_INTENTS = 5;
export const DEMO_EXTRA_ITEMS = 5;

export const DEMO_REPORT_TITLES: readonly { title: string; metric: string }[] = [
  { title: "Monthly cost by agent (estimated)", metric: "cost" },
  { title: "Coverage trend, last 30 days", metric: "coverage" },
  { title: "Latency p95 by model", metric: "latency" },
];
