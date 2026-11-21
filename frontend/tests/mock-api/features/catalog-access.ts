import type { FeatureMockContext, FeatureMockHandler } from "./context.ts";

/**
 * PRP-73 item 5: catalog data access mock (SYNTHETIC data only). Imitates the outcomes of
 * services/api/neurosphere_api/catalog/access/router.py for the three routes:
 *
 *   POST /api/v1/catalog/access/query        who read or wrote the named or filtered assets
 *   POST /api/v1/catalog/access/dependents   what depends on a node, grouped by depth
 *   GET  /api/v1/catalog/access/region-groups
 *
 * Deterministic triggers (stateless, repeatable):
 * - an asset id of ACCESS_ASSET_EMPTY answers no rows; ACCESS_ASSET_TRUNCATED answers a partial
 *   result (`max_assets`); ACCESS_ASSET_FORBIDDEN answers 403 forbidden;
 * - `include_unassessed: true` adds assets whose values are null (reported as not assessed);
 * - an unknown `region_group` answers 422 `unknown_region_group`; more than 50 asset ids answer
 *   422 `too_many_assets`;
 * - dependents: ACCESS_NODE_EMPTY answers none, ACCESS_NODE_TRUNCATED a partial walk
 *   (`max_depth`), ACCESS_NODE_FORBIDDEN 403; a depth above 5 is 422 `max_depth_exceeded`, a
 *   depth below 1 `invalid_depth`.
 * Every route needs a token (401 otherwise). Both the canonical path and the `/catalog/access`
 * alias prefix are the same under `/api/v1/catalog`.
 */

const PREFIX = "commercial:e2e:catalog:";
const DOMAIN = "commercial:e2e:sandbox:domain:finance";
const NOW = "2026-10-20T12:00:00Z";
const MAX_ASSET_IDS = 50;

export const ACCESS_ASSET_LEDGER = `${PREFIX}grounding_source:ledger-store`;
export const ACCESS_ASSET_EMPTY = `${PREFIX}grounding_source:empty-store`;
export const ACCESS_ASSET_TRUNCATED = `${PREFIX}grounding_source:huge-store`;
export const ACCESS_ASSET_FORBIDDEN = `${PREFIX}grounding_source:restricted-store`;
export const ACCESS_NODE_SERVICE = `${PREFIX}service:ledger`;
export const ACCESS_NODE_EMPTY = `${PREFIX}service:idle`;
export const ACCESS_NODE_TRUNCATED = `${PREFIX}service:busy`;
export const ACCESS_NODE_FORBIDDEN = `${PREFIX}service:restricted`;
export const ACCESS_REGION_GROUPS = [
  { name: "eu", regions: ["francecentral", "germanywestcentral", "swedencentral"] },
  {
    name: "europe",
    regions: ["francecentral", "northeurope", "swedencentral", "westeurope"],
  },
] as const;

interface Row {
  asset_id: string;
  accessor_id: string;
  accessor_type: string;
  accessor_name: string;
  accessor_domain_id: string | null;
  mode: "read" | "write" | null;
  relation: string;
  edge_id: string;
  status: "asserted" | "inferred" | "curated";
  confidence: number;
  provenance_method: string;
  provenance_source_id: string;
  evidence_ids: string[];
  last_observed: string;
  depth: number;
  relation_path: string[];
  path_node_ids: string[];
}

function accessRow(
  asset: string,
  agent: string,
  name: string,
  mode: "read" | "write",
  status: Row["status"],
  confidence: number,
  evidence: string[],
): Row {
  const accessor = `${PREFIX}agent:${agent}`;
  const relation = mode === "write" ? "writes" : "reads";
  return {
    asset_id: asset,
    accessor_id: accessor,
    accessor_type: "agent",
    accessor_name: name,
    accessor_domain_id: DOMAIN,
    mode,
    relation,
    edge_id: `commercial:e2e:edge:${agent}:${relation}:${asset.split(":").pop() ?? ""}`,
    status,
    confidence,
    provenance_method: status === "inferred" ? "data_source_ref" : "declared",
    provenance_source_id: status === "inferred" ? "telemetry" : "catalog",
    evidence_ids: evidence,
    last_observed: NOW,
    depth: 1,
    relation_path: [relation],
    path_node_ids: [accessor, asset],
  };
}

function normalRows(asset: string, modes: readonly string[]): Row[] {
  const all = [
    accessRow(asset, "budget-bot", "Budget bot", "write", "asserted", 0.95, [
      "trace:a1",
      "trace:a2",
    ]),
    accessRow(asset, "sample-agent", "Sample agent", "write", "inferred", 0.7, ["trace:b1"]),
    accessRow(asset, "report-agent", "Report agent", "read", "curated", 1, []),
  ];
  return all.filter((r) => r.mode !== null && modes.includes(r.mode));
}

function asset(id: string, name: string, over: Record<string, unknown> = {}) {
  return {
    id,
    display_name: name,
    domain_id: DOMAIN,
    classification: "confidential",
    residency_region: "swedencentral",
    contains_personal_data: true,
    sensitivity_categories: ["pii"],
    ...over,
  };
}

const UNASSESSED = [
  asset(`${PREFIX}grounding_source:legacy-store`, "Legacy store", {
    classification: null,
    residency_region: null,
    contains_personal_data: null,
    sensitivity_categories: null,
  }),
  asset(`${PREFIX}grounding_source:scratch-store`, "Scratch store", {
    contains_personal_data: null,
    sensitivity_categories: [],
  }),
];

const BOUND = { max_assets: 200, max_accessors: 500, timeout_ms: 5000 };

function send(ctx: FeatureMockContext, status: number, body: unknown): void {
  ctx.res.writeHead(status, { "content-type": "application/json", ...ctx.cors });
  ctx.res.end(JSON.stringify(body));
}

function parse(raw: string): Record<string, unknown> {
  try {
    const value: unknown = JSON.parse(raw === "" ? "{}" : raw);
    return typeof value === "object" && value !== null && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

function queryResponse(body: Record<string, unknown>) {
  const ids = Array.isArray(body["asset_ids"]) ? (body["asset_ids"] as string[]) : [];
  const modes = Array.isArray(body["modes"]) ? (body["modes"] as string[]) : ["read", "write"];
  const unassessed = body["include_unassessed"] === true;
  const target = ids[0] ?? ACCESS_ASSET_LEDGER;
  const empty = target === ACCESS_ASSET_EMPTY;
  const partial = target === ACCESS_ASSET_TRUNCATED;
  const rows = empty ? [] : normalRows(target, modes);
  return {
    rows,
    assets: empty ? [] : [asset(target, "Ledger store")],
    unassessed_assets: unassessed ? UNASSESSED : null,
    unassessed_count: unassessed ? UNASSESSED.length : null,
    truncated: partial,
    truncated_reason: partial ? "max_assets" : null,
    assets_scanned: partial ? 200 : empty ? 1 : 3,
    bound: BOUND,
  };
}

function dependentRow(
  node: string,
  kind: string,
  name: string,
  depth: number,
  path: string[],
): Row {
  const id = `${PREFIX}${kind}:${name.toLowerCase().replace(/\s+/g, "-")}`;
  return {
    asset_id: node,
    accessor_id: id,
    accessor_type: kind,
    accessor_name: name,
    accessor_domain_id: DOMAIN,
    mode: null,
    relation: path[0] ?? "invokes",
    edge_id: `commercial:e2e:edge:${name.toLowerCase().replace(/\s+/g, "-")}:${depth}`,
    status: depth === 1 ? "asserted" : "inferred",
    confidence: depth === 1 ? 1 : 0.8,
    provenance_method: "declared",
    provenance_source_id: "catalog",
    evidence_ids: [`trace:dep-${String(depth)}`],
    last_observed: NOW,
    depth,
    relation_path: path,
    path_node_ids: [id, node],
  };
}

function dependentsResponse(nodeId: string, maxDepth: number) {
  const empty = nodeId === ACCESS_NODE_EMPTY;
  const partial = nodeId === ACCESS_NODE_TRUNCATED;
  const all = [
    dependentRow(nodeId, "agent", "Budget bot", 1, ["invokes"]),
    dependentRow(nodeId, "agent", "Report agent", 2, ["invokes", "uses_tool"]),
    dependentRow(nodeId, "agent", "Forecast agent", 2, ["invokes", "uses_tool"]),
    dependentRow(nodeId, "service", "Gateway", 3, ["invokes", "uses_tool", "routes_to"]),
  ];
  const rows = empty ? [] : all.filter((r) => r.depth <= maxDepth);
  const depths = [...new Set(rows.map((r) => r.depth))].sort((a, b) => a - b);
  return {
    groups: depths.map((depth) => ({ depth, rows: rows.filter((r) => r.depth === depth) })),
    total: rows.length,
    truncated: partial,
    truncated_reason: partial ? "max_depth" : null,
    assets_scanned: partial ? 5000 : rows.length,
    bound: { ...BOUND, max_depth: maxDepth },
  };
}

function handleQuery(ctx: FeatureMockContext, body: Record<string, unknown>): void {
  const ids = Array.isArray(body["asset_ids"]) ? (body["asset_ids"] as string[]) : [];
  const filters = (body["filters"] ?? {}) as Record<string, unknown>;
  const group = filters["region_group"];
  if (ids.includes(ACCESS_ASSET_FORBIDDEN)) {
    ctx.forbidden();
    return;
  }
  if (ids.length > MAX_ASSET_IDS) {
    ctx.problem(422, "invalid_schema", "too_many_assets", "Too many asset ids.");
    return;
  }
  if (typeof group === "string" && !ACCESS_REGION_GROUPS.some((g) => g.name === group)) {
    ctx.problem(422, "invalid_schema", "unknown_region_group", "Unknown region group.");
    return;
  }
  send(ctx, 200, queryResponse(body));
}

function handleDependents(ctx: FeatureMockContext, body: Record<string, unknown>): void {
  const nodeId = typeof body["node_id"] === "string" ? body["node_id"] : "";
  const depth = body["max_depth"];
  if (nodeId === ACCESS_NODE_FORBIDDEN) {
    ctx.forbidden();
    return;
  }
  if (typeof depth !== "number" || !Number.isInteger(depth) || depth < 1) {
    ctx.problem(422, "invalid_schema", "invalid_depth", "max_depth must be 1 to 5.");
    return;
  }
  if (depth > 5) {
    ctx.problem(422, "invalid_schema", "max_depth_exceeded", "max_depth must be 1 to 5.");
    return;
  }
  send(ctx, 200, dependentsResponse(nodeId, depth));
}

export const handle: FeatureMockHandler = (ctx) => {
  // The registry test calls every handler with an empty object: nothing to answer then.
  const url = (ctx as { url?: URL }).url;
  if (url === undefined) return false;
  const route = /^\/api\/v1\/catalog\/access\/(query|dependents|region-groups)$/.exec(
    url.pathname,
  )?.[1];
  if (route === undefined) return false;
  const method = ctx.req.method ?? "GET";
  if ((route === "region-groups") !== (method === "GET")) return false;
  if (!ctx.authorized) {
    send(ctx, 401, { error: "missing or unrecognised token" });
    return true;
  }
  if (route === "region-groups") {
    send(ctx, 200, { groups: ACCESS_REGION_GROUPS });
    return true;
  }
  void ctx.readBody().then((raw) => {
    const body = parse(raw);
    if (route === "query") handleQuery(ctx, body);
    else handleDependents(ctx, body);
  });
  return true;
};
