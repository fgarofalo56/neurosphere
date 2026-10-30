import {
  DOMAIN_OK,
  DOMAIN_VIEWER,
  INTENT_ADVISORY,
  ITEM_MAKER_CHECKER,
  REC_RIGHT_SIZING,
  TRACE_COMPLETE,
} from "../../mock-api/server.ts";

// PRP-24 item 3: one or more concrete URLs for EVERY pattern in src/app/route-manifest.json. The
// spec fails when a manifest pattern has no sample here (or a sample names a pattern that is not
// in the manifest), so a new route cannot ship without an axe test.

export interface RouteSample {
  /** Pattern from route-manifest.json. */
  readonly pattern: string;
  /** Short label, unique per pattern. */
  readonly name: string;
  /** Concrete URL the mock API can serve. */
  readonly url: string;
  /** Selector that must be visible before axe runs (the state the page settles in). */
  readonly ready: string;
  /** Token persona for lanes whose spec needs one (`/audit` is an auditor-only page). */
  readonly persona?: string;
}

const domain = encodeURIComponent(DOMAIN_OK);
const q = (extra = ""): string => `domain_id=${domain}${extra}`;
const REPORT_ID = "rpt-seed-own";
const ENTITY_ID = "commercial:e2e:catalog:agent:sample-agent";
const EDGE_ID = "commercial:e2e:edge:sample-agent/uses/sample-model";
const MCP_SERVER_ID = `mcp-${"a".repeat(32)}`;

export const ROUTE_SAMPLES: readonly RouteSample[] = [
  { pattern: "/", name: "home", url: `/?${q()}`, ready: "[data-testid='tile-cost']" },
  { pattern: "/actions", name: "actions list", url: `/actions?${q()}`, ready: "main h1" },
  {
    pattern: "/actions/detail",
    name: "action detail",
    url: `/actions/detail?${q(`&intent_id=${INTENT_ADVISORY}`)}`,
    ready: "main h1",
  },
  {
    pattern: "/actions/propose",
    name: "action propose",
    url: `/actions/propose?${q()}`,
    ready: "main h1",
  },
  {
    pattern: "/catalog/publication",
    name: "catalog publication",
    url: `/catalog/publication?${q()}`,
    ready: "main h1",
  },
  { pattern: "/dashboards/cost", name: "cost", url: `/dashboards/cost?${q()}`, ready: "main h1" },
  {
    pattern: "/dashboards/coverage",
    name: "coverage",
    url: `/dashboards/coverage?${q()}`,
    ready: "main h1",
  },
  {
    pattern: "/dashboards/latency",
    name: "latency",
    url: `/dashboards/latency?${q()}`,
    ready: "main h1",
  },
  { pattern: "/gateways", name: "gateways", url: `/gateways?${q()}`, ready: "main h1" },
  {
    pattern: "/map",
    name: "map",
    url: `/map?${q()}`,
    ready: "[data-testid='map-canvas'][data-node-count]:not([data-node-count='0'])",
  },
  {
    pattern: "/map/table",
    name: "map table",
    url: `/map/table?${q()}`,
    ready: "[role='treegrid']",
  },
  { pattern: "/mcp-admin", name: "mcp admin", url: "/mcp-admin", ready: "main h1" },
  {
    pattern: "/mcp-admin/server",
    name: "mcp server",
    url: `/mcp-admin/server?server_id=${MCP_SERVER_ID}`,
    ready: "main h1",
  },
  { pattern: "/quality", name: "quality", url: `/quality?${q()}`, ready: "main h1" },
  {
    pattern: "/recommendations",
    name: "recommendations list",
    url: `/recommendations?${q()}`,
    ready: "main h1",
  },
  {
    pattern: "/recommendations/detail",
    name: "recommendation detail",
    url: `/recommendations/detail?${q(`&recommendation_id=${encodeURIComponent(REC_RIGHT_SIZING)}`)}`,
    ready: "main h1",
  },
  {
    pattern: "/reconciliation",
    name: "reconciliation",
    url: `/reconciliation?${q()}`,
    ready: "main h1",
  },
  {
    pattern: "/replay/traces",
    name: "trace replay",
    url: `/replay/traces?${q(`&trace_id=${TRACE_COMPLETE}`)}`,
    ready: "main h1",
  },
  { pattern: "/reports", name: "reports list", url: `/reports?${q()}`, ready: "main h1" },
  {
    pattern: "/reports/view",
    name: "report view",
    url: `/reports/view?${q(`&report_id=${REPORT_ID}`)}`,
    ready: "main h1",
  },
  { pattern: "/review", name: "review list", url: `/review?${q()}`, ready: "main h1" },
  {
    pattern: "/review/item",
    name: "review item",
    url: `/review/item?${q(`&item_id=${ITEM_MAKER_CHECKER}`)}`,
    ready: "main h1",
  },
  { pattern: "/sandbox", name: "sandbox page", url: `/sandbox?${q()}`, ready: "main h1" },
  {
    pattern: "/workspaces/admin",
    name: "admin workspace",
    url: `/workspaces/admin?${q()}`,
    ready: "main h1",
  },
  {
    pattern: "/workspaces/analyst",
    name: "analyst workspace",
    url: `/workspaces/analyst?${q()}`,
    ready: "main h1",
  },
  {
    pattern: "/workspaces/auditor",
    name: "auditor workspace",
    url: `/workspaces/auditor?${q()}`,
    ready: "main h1",
  },
  {
    pattern: "/workspaces/steward",
    name: "steward workspace",
    url: `/workspaces/steward?${q()}`,
    ready: "main h1",
  },
  {
    pattern: "/workspaces/viewer",
    name: "viewer workspace",
    url: `/workspaces/viewer?domain_id=${encodeURIComponent(DOMAIN_VIEWER)}`,
    ready: "main h1",
  },
  {
    pattern: "/catalog",
    name: "catalog explorer",
    url: `/catalog?${q()}`,
    ready: "main h1",
  },
  {
    pattern: "/catalog/entity",
    name: "catalog entity",
    url: `/catalog/entity?${q(`&entity_id=${encodeURIComponent(ENTITY_ID)}`)}`,
    ready: "main h1",
  },
  {
    pattern: "/catalog/edge",
    name: "relationship edge",
    url: `/catalog/edge?${q(`&edge_id=${encodeURIComponent(EDGE_ID)}`)}`,
    ready: "main h1",
  },
  {
    pattern: "/catalog/recertifications",
    name: "recertifications",
    url: `/catalog/recertifications?${q()}`,
    ready: "main h1",
  },
  {
    pattern: "/catalog/stale-agents",
    name: "stale agents",
    url: `/catalog/stale-agents?${q()}`,
    ready: "main h1",
  },
  {
    pattern: "/audit",
    name: "audit log",
    url: `/audit?audit_domain=${domain}`,
    ready: "main h1",
    persona: "auditor",
  },
  {
    pattern: "/finops/forecast",
    name: "finops forecast",
    url: `/finops/forecast?${q()}`,
    ready: "main h1",
  },
  {
    pattern: "/federation",
    name: "federation",
    url: `/federation?${q()}`,
    ready: "main h1",
  },
  {
    pattern: "/deploy",
    name: "deployment",
    url: `/deploy?${q()}`,
    ready: "main h1",
  },
  {
    pattern: "/deploy/capabilities",
    name: "deployment capabilities",
    url: `/deploy/capabilities?${q()}`,
    ready: "main h1",
  },
  {
    pattern: "/evaluations",
    name: "evaluation results",
    url: `/evaluations?${q()}`,
    ready: "main h1",
  },
  {
    pattern: "/admin/execution-control",
    name: "execution control",
    url: `/admin/execution-control?${q()}`,
    ready: "main h1",
  },
];

/** Representative routes for the theme pack matrix (home, a dashboard, map table, reports view, sandbox). */
export const THEME_MATRIX_PATTERNS = [
  "/",
  "/dashboards/cost",
  "/map/table",
  "/reports/view",
  "/sandbox",
] as const;
