/**
 * Static fixture data for the PRP-30 mockup gallery. Synthetic, deterministic, no network.
 * Demo-only: this folder is reachable only through the demo dynamic import.
 */
import type { ChartSeries, HealthState, NodeType } from "../../../design-system";

/** The fixed clock every mockup renders against. */
export const MOCKUP_NOW = "2026-10-24T12:00:00Z";

/** Side navigation groups with a few sample labels each (group names mirror app/navigation.ts). */
export const NAV_SAMPLE: readonly { group: string; items: readonly string[] }[] = [
  { group: "Overview", items: ["Home", "Map", "Session replay"] },
  { group: "Cost & usage", items: ["Cost dashboard", "Budgets"] },
  { group: "Agents", items: ["Catalog", "Relationships"] },
  { group: "Quality", items: ["Recommendations", "Evaluations"] },
  { group: "Governance", items: ["Review queue", "Actions", "Audit"] },
  { group: "Reports", items: ["Reports", "Copilot"] },
];

function days(start: string, count: number): string[] {
  const t0 = Date.parse(start);
  return Array.from({ length: count }, (_, i) => new Date(t0 + i * 86_400_000).toISOString());
}

const DAYS = days("2026-10-10T00:00:00Z", 14);

function points(
  values: readonly (number | null)[],
  incompleteAt: readonly number[] = [],
): ChartSeries["points"] {
  return DAYS.map((t, i) => ({
    t,
    value: values[i] ?? null,
    complete: !incompleteAt.includes(i),
  }));
}

const USD_BASE = [
  6120, 6480, 6310, 5990, 6720, 7010, 6850, 6540, 6930, 7280, 7150, 6890, 7420, 7060,
];
const USD_INVOICED = [
  5980,
  6390,
  6240,
  5870,
  6610,
  null,
  6700,
  6470,
  6820,
  7120,
  7040,
  6710,
  null,
  null,
];
const EUR_BASE = [
  1710, 1780, 1690, 1640, 1820, 1900, 1860, 1790, 1850, 1930, 1880, 1840, 1960, 1910,
];
const EUR_INVOICED = [
  1680,
  1750,
  1670,
  1620,
  1790,
  1870,
  1830,
  1760,
  1810,
  1890,
  1860,
  null,
  null,
  null,
];

/** Estimates run about 12% above the invoiced series so the two lines read as separate. */
const USD_ESTIMATED = USD_BASE.map((v) => Math.round(v * 1.12));
const EUR_ESTIMATED = EUR_BASE.map((v) => Math.round(v * 1.12));

export const USD_SERIES: readonly ChartSeries[] = [
  {
    key: "usd-estimated",
    label: "Azure OpenAI",
    kind: "estimated",
    unit: "currency",
    currency: "USD",
    points: points(USD_ESTIMATED, [13]),
  },
  {
    key: "usd-invoiced",
    label: "Azure OpenAI",
    kind: "invoiced",
    unit: "currency",
    currency: "USD",
    points: points(USD_INVOICED, [11]),
  },
];

export const EUR_SERIES: readonly ChartSeries[] = [
  {
    key: "eur-estimated",
    label: "Azure OpenAI EU",
    kind: "estimated",
    unit: "currency",
    currency: "EUR",
    points: points(EUR_ESTIMATED, [13]),
  },
  {
    key: "eur-invoiced",
    label: "Azure OpenAI EU",
    kind: "invoiced",
    unit: "currency",
    currency: "EUR",
    points: points(EUR_INVOICED, [10]),
  },
];

/** Last 7 days of estimated daily cost, per currency, for the home sparklines. */
export const USD_LAST_7: readonly (number | null)[] = USD_ESTIMATED.slice(7);
export const EUR_LAST_7: readonly (number | null)[] = EUR_ESTIMATED.slice(7);
export const USD_TOTAL_7 = USD_ESTIMATED.slice(7).reduce((a, b) => a + b, 0);
export const EUR_TOTAL_7 = EUR_ESTIMATED.slice(7).reduce((a, b) => a + b, 0);

export interface CostRow {
  readonly day: string;
  readonly currency: "USD" | "EUR";
  readonly estimated: number | null;
  readonly invoiced: number | null;
  readonly complete: boolean;
}

/** Table rows built from the same numbers as the charts; newest first. */
export const COST_ROWS: readonly CostRow[] = [
  ...USD_ESTIMATED.map((est, i) => ({
    day: DAYS[i] ?? "",
    currency: "USD" as const,
    estimated: est,
    invoiced: USD_INVOICED[i] ?? null,
    complete: i !== 13,
  })),
  ...EUR_ESTIMATED.map((est, i) => ({
    day: DAYS[i] ?? "",
    currency: "EUR" as const,
    estimated: est,
    invoiced: EUR_INVOICED[i] ?? null,
    complete: i !== 13,
  })),
]
  .filter((r) => DAYS.indexOf(r.day) >= 10)
  .sort((a, b) =>
    a.day === b.day ? a.currency.localeCompare(b.currency) : b.day.localeCompare(a.day),
  );

export interface ActivityRow {
  readonly id: string;
  readonly item: string;
  readonly kind: string;
  readonly state: "Pending review" | "Awaiting approval" | "Applied" | "Failed";
  readonly at: string;
}

export const ACTIVITY_ROWS: readonly ActivityRow[] = [
  {
    id: "a1",
    item: "Swap gpt-4o to gpt-4o-mini on support-triage",
    kind: "Model change",
    state: "Awaiting approval",
    at: "2026-10-24T11:20:00Z",
  },
  {
    id: "a2",
    item: "Retire unused tool: legacy-search",
    kind: "Catalog",
    state: "Pending review",
    at: "2026-10-24T09:05:00Z",
  },
  {
    id: "a3",
    item: "Raise budget alert for finance-copilot",
    kind: "Budget",
    state: "Applied",
    at: "2026-10-23T16:40:00Z",
  },
  {
    id: "a4",
    item: "Rotate connector credential reference",
    kind: "Connector",
    state: "Failed",
    at: "2026-10-23T08:15:00Z",
  },
  {
    id: "a5",
    item: "Link planner-agent to retrieval-index",
    kind: "Relationship",
    state: "Pending review",
    at: "2026-10-22T14:30:00Z",
  },
];

export interface MapNode {
  readonly id: string;
  readonly label: string;
  readonly type: NodeType;
  readonly x: number;
  readonly y: number;
  readonly health: HealthState;
}

/** Hand-placed layout on a 1000 x 560 canvas. */
export const MAP_NODES: readonly MapNode[] = [
  { id: "p1", label: "Platform team", type: "person", x: 90, y: 90, health: "ok" },
  { id: "p2", label: "Finance ops", type: "person", x: 90, y: 270, health: "ok" },
  { id: "p3", label: "Support leads", type: "person", x: 90, y: 450, health: "unknown" },
  { id: "a1", label: "support-triage", type: "agent", x: 290, y: 70, health: "degraded" },
  { id: "a2", label: "finance-copilot", type: "agent", x: 290, y: 230, health: "ok" },
  { id: "a3", label: "planner-agent", type: "agent", x: 290, y: 390, health: "ok" },
  { id: "a4", label: "report-writer", type: "agent", x: 290, y: 510, health: "failing" },
  { id: "s1", label: "classifier", type: "sub-agent", x: 470, y: 40, health: "ok" },
  { id: "s2", label: "summariser", type: "sub-agent", x: 470, y: 150, health: "ok" },
  { id: "s3", label: "ledger-reader", type: "sub-agent", x: 470, y: 270, health: "degraded" },
  { id: "s4", label: "task-splitter", type: "sub-agent", x: 470, y: 380, health: "ok" },
  { id: "s5", label: "chart-builder", type: "sub-agent", x: 470, y: 490, health: "unknown" },
  { id: "m1", label: "gpt-4o", type: "model", x: 680, y: 60, health: "ok" },
  { id: "m2", label: "gpt-4o-mini", type: "model", x: 680, y: 160, health: "ok" },
  { id: "m3", label: "text-embedding-3", type: "model", x: 680, y: 260, health: "ok" },
  { id: "m4", label: "phi-4", type: "model", x: 680, y: 360, health: "degraded" },
  { id: "m5", label: "o4-mini", type: "model", x: 680, y: 460, health: "ok" },
  { id: "d1", label: "tickets-db", type: "source", x: 890, y: 40, health: "ok" },
  { id: "d2", label: "ledger-export", type: "source", x: 890, y: 130, health: "degraded" },
  { id: "d3", label: "retrieval-index", type: "source", x: 890, y: 220, health: "ok" },
  { id: "d4", label: "policy-docs", type: "source", x: 890, y: 310, health: "ok" },
  { id: "d5", label: "billing-feed", type: "source", x: 890, y: 400, health: "failing" },
  { id: "d6", label: "wiki", type: "source", x: 890, y: 490, health: "unknown" },
  { id: "a5", label: "intake-bot", type: "agent", x: 180, y: 540, health: "ok" },
  { id: "s6", label: "pii-filter", type: "sub-agent", x: 580, y: 110, health: "ok" },
  { id: "m6", label: "rerank-v3", type: "model", x: 580, y: 530, health: "unknown" },
];

/** Provenance edges as [from, to] node ids. */
export const MAP_EDGES: readonly (readonly [string, string])[] = [
  ["p1", "a1"],
  ["p1", "a3"],
  ["p2", "a2"],
  ["p3", "a1"],
  ["p3", "a4"],
  ["a1", "s1"],
  ["a1", "s2"],
  ["a2", "s3"],
  ["a3", "s4"],
  ["a4", "s5"],
  ["a4", "s2"],
  ["s1", "m1"],
  ["s2", "m2"],
  ["s3", "m3"],
  ["s4", "m4"],
  ["s5", "m5"],
  ["s1", "s6"],
  ["s6", "m1"],
  ["m1", "d1"],
  ["m2", "d2"],
  ["m3", "d3"],
  ["m3", "d4"],
  ["m4", "d4"],
  ["m5", "d5"],
  ["m5", "d6"],
  ["s3", "d2"],
  ["a3", "m6"],
  ["a5", "m6"],
  ["m6", "d3"],
];
