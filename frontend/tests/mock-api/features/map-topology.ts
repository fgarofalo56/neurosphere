import type { FeatureMockContext, FeatureMockHandler } from "./context.ts";

/**
 * PRP-77 live-map mock: viewport (with facets and the PRP-74 filter parameters), search (matches
 * plus counts), neighbourhood and impact for ONE fixture domain family, plus a test-only control
 * route that flips a node's health, adds a node or resets the fixture. Every other request is
 * passed through unchanged (the handler returns false), so no other domain's behaviour changes.
 *
 * The family is `DOMAIN_MAP_INCIDENT` and `incidentDomain(suffix)` (same fixture, separate
 * state), so specs that mutate the fixture run in parallel without seeing each other. State is
 * module-level; the Playwright mock server is one process, so a spec drives it through the control
 * route (`POST .../__e2e/control`), and unit tests call `resetMapTopology()`.
 *
 * Shapes follow services/api/neurosphere_api/map/models.py (PRP-74) and `@neurosphere/contracts`
 * `MapNodeFacets`. Every id and value is SYNTHETIC.
 *
 * Dependents: an edge `source -> target` means source depends on target, so the impact of a node is
 * the set of sources reachable by walking edges backwards.
 */

export const DOMAIN_MAP_INCIDENT = "commercial:e2e:sandbox:domain:map-incident";
const DOMAIN_FAMILY = /^commercial:e2e:sandbox:domain:map-incident(-[a-z0-9]+(-[a-z0-9]+)*)?$/;

/** Another instance of the same fixture with its own state (lower-case letters, digits and single hyphens). */
export function incidentDomain(suffix: string): string {
  return `${DOMAIN_MAP_INCIDENT}-${suffix}`;
}

const MAP_ROOT = /^\/api\/v1\/map\/domains\/([^/]+)\/(viewport|search|impact|__e2e\/control)\/?$/;
const NEIGHBORHOOD = /^\/api\/v1\/map\/domains\/([^/]+)\/neighborhood\/(.+)$/;

/** Ids of the fixture nodes, so specs name them without retyping strings. */
export const INCIDENT_IDS = {
  ledger: "inc:service:ledger",
  billing: "inc:agent:billing",
  refund: "inc:agent:refund",
  reconcile: "inc:sub_agent:reconcile",
  report: "inc:agent:report",
  archive: "inc:agent:archive",
  tax: "inc:tool:tax",
  docs: "inc:mcp_server:docs",
  gpt: "inc:model:gpt",
  kb: "inc:source:kb",
  person: "inc:person:1",
  notify: "inc:agent:notify",
  queue: "inc:service:queue",
} as const;

type Health = "ok" | "degraded" | "failing" | "unknown";
type Kind =
  "agent" | "sub_agent" | "model" | "source" | "person" | "service" | "tool" | "mcp_server";

export interface IncidentNode {
  id: string;
  kind: Kind;
  label: string;
  environment: string;
  cloud: "commercial" | "government" | null;
  tags: string[];
  health: Health;
  errorRate: number | null;
  /** False: not in the viewport; reachable only through search, neighbourhood and impact. */
  inViewport: boolean;
}
interface IncidentEdge {
  id: string;
  source: string;
  target: string;
  provenance: "observed" | "declared" | "inferred";
}
interface DomainState {
  nodes: IncidentNode[];
  edges: IncidentEdge[];
}

const AS_OF = "2026-11-20T10:00:00Z";
const ERROR_AT = "2026-11-20T09:58:00Z";

function node(
  id: string,
  kind: Kind,
  label: string,
  environment: string,
  cloud: IncidentNode["cloud"],
  health: Health,
  over: Partial<IncidentNode> = {},
): IncidentNode {
  return {
    id,
    kind,
    label,
    environment,
    cloud,
    health,
    tags: [],
    errorRate: null,
    inViewport: true,
    ...over,
  };
}

function initialState(): DomainState {
  const I = INCIDENT_IDS;
  return {
    nodes: [
      node(I.ledger, "service", "ledger-service", "production", "commercial", "failing", {
        tags: ["payments"],
        errorRate: 0.31,
      }),
      node(I.billing, "agent", "billing-agent", "production", "commercial", "ok", {
        tags: ["payments"],
        errorRate: 0.01,
      }),
      node(I.refund, "agent", "refund-agent", "production", "commercial", "ok", {
        tags: ["payments"],
      }),
      node(I.reconcile, "sub_agent", "reconcile-sub-agent", "production", "commercial", "ok"),
      node(I.report, "agent", "report-agent", "staging", "commercial", "ok"),
      node(I.archive, "agent", "archive-agent", "production", "commercial", "ok", {
        inViewport: false,
      }),
      node(I.tax, "tool", "tax-tool", "staging", "commercial", "ok"),
      node(I.docs, "mcp_server", "docs-mcp", "production", "government", "ok"),
      node(I.gpt, "model", "support-gpt", "staging", "commercial", "degraded", {
        errorRate: 0.04,
      }),
      node(I.kb, "source", "knowledge-base", "development", "commercial", "ok"),
      node(I.person, "person", "Person-3fa9", "unknown", null, "unknown"),
      node(I.notify, "agent", "notify-agent", "production", "commercial", "ok"),
      node(I.queue, "service", "queue-service", "staging", "commercial", "ok"),
    ],
    edges: [
      edge(I.billing, I.ledger, "observed"),
      edge(I.refund, I.ledger, "observed"),
      edge(I.reconcile, I.billing, "declared"),
      edge(I.report, I.refund, "observed"),
      edge(I.archive, I.refund, "inferred"),
      edge(I.billing, I.tax, "observed"),
      edge(I.billing, I.gpt, "declared"),
      edge(I.notify, I.queue, "observed"),
      edge(I.notify, I.docs, "declared"),
      edge(I.person, I.notify, "observed"),
      edge(I.refund, I.kb, "inferred"),
    ],
  };
}

function edge(
  source: string,
  target: string,
  provenance: IncidentEdge["provenance"],
): IncidentEdge {
  return { id: `inc:edge:${source.slice(4)}>${target.slice(4)}`, source, target, provenance };
}

const states = new Map<string, DomainState>();

/** Restores the fixture (all instances). */
export function resetMapTopology(): void {
  states.clear();
}

function stateOf(domain: string): DomainState {
  let s = states.get(domain);
  if (s === undefined) {
    s = initialState();
    states.set(domain, s);
  }
  return s;
}

// ---- wire shapes --------------------------------------------------------------------------

function wireNode(n: IncidentNode): Record<string, unknown> {
  return {
    id: n.id,
    kind: n.kind,
    label: n.label,
    cluster_id: null,
    member_count: null,
    metrics: {
      tokens: n.health === "unknown" ? null : 1200,
      context_size: n.health === "unknown" ? null : 8192,
      frequency: n.health === "unknown" ? null : 3,
      latency_p95_ms: n.health === "unknown" ? null : 400,
      health: n.health,
    },
    facets: {
      entity_type:
        n.kind === "sub_agent" ? "agent" : n.kind === "model" ? "model_deployment" : n.kind,
      environment: n.environment,
      cloud: n.cloud,
      tags: n.tags,
      discovery: "declared",
      health: n.health,
      error_rate: n.errorRate,
      error_count: n.errorRate === null ? null : Math.round(n.errorRate * 100),
      request_count: n.errorRate === null ? null : 100,
      last_error_at: n.errorRate !== null && n.errorRate > 0.1 ? ERROR_AT : null,
    },
  };
}

function wireEdge(e: IncidentEdge): Record<string, unknown> {
  return {
    id: e.id,
    source: e.source,
    target: e.target,
    provenance: e.provenance,
    last_observed_at: e.provenance === "observed" ? AS_OF : null,
  };
}

const COVERAGE = { state: "complete", lag_seconds: 0, as_of: AS_OF };

interface Filters {
  node_type: string | null;
  tag: string | null;
  environment: string | null;
  cloud: string | null;
  health: string | null;
}

function filtersOf(url: URL): Filters {
  const get = (name: string): string | null => {
    const v = url.searchParams.get(name);
    return v === null || v === "" ? null : v;
  };
  return {
    node_type: get("node_type"),
    tag: get("tag"),
    environment: get("environment"),
    cloud: get("cloud"),
    health: get("health"),
  };
}

function matchesFilters(n: IncidentNode, f: Filters): boolean {
  if (f.node_type !== null && n.kind !== f.node_type) return false;
  if (f.tag !== null && !n.tags.includes(f.tag)) return false;
  if (f.environment !== null && n.environment !== f.environment) return false;
  if (f.cloud !== null && n.cloud !== f.cloud) return false;
  if (f.health !== null && n.health !== f.health) return false;
  return true;
}

function tally(nodes: readonly IncidentNode[]): Record<string, Record<string, number>> {
  const bump = (bucket: Record<string, number>, key: string): void => {
    bucket[key] = (bucket[key] ?? 0) + 1;
  };
  const counts = { by_kind: {}, by_health: {}, by_environment: {}, by_cloud: {} } as Record<
    string,
    Record<string, number>
  >;
  for (const n of nodes) {
    bump(counts["by_kind"] ?? {}, n.kind);
    bump(counts["by_health"] ?? {}, n.health);
    bump(counts["by_environment"] ?? {}, n.environment);
    if (n.cloud !== null) bump(counts["by_cloud"] ?? {}, n.cloud);
  }
  return counts;
}

function viewport(domain: string, url: URL): Record<string, unknown> {
  const s = stateOf(domain);
  const f = filtersOf(url);
  // The fixture has no clusters: an expansion request is an empty page.
  const clusterId = url.searchParams.get("cluster_id");
  const nodes =
    clusterId === null || clusterId === ""
      ? s.nodes.filter((n) => n.inViewport && matchesFilters(n, f))
      : [];
  const ids = new Set(nodes.map((n) => n.id));
  const hidden = s.nodes.some((n) => !n.inViewport);
  return {
    domain_id: domain,
    nodes: nodes.map(wireNode),
    edges: s.edges.filter((e) => ids.has(e.source) && ids.has(e.target)).map(wireEdge),
    truncated: hidden,
    truncation_reason: hidden ? "node_budget" : null,
    next_cursor: null,
    coverage: COVERAGE,
  };
}

function search(domain: string, url: URL): Record<string, unknown> {
  const s = stateOf(domain);
  const f = filtersOf(url);
  const needle = (url.searchParams.get("q") ?? "").trim().toLowerCase();
  const limitRaw = Number(url.searchParams.get("limit"));
  const limit = Number.isInteger(limitRaw) && limitRaw >= 1 ? Math.min(limitRaw, 50) : 20;
  const hits = s.nodes.filter(
    (n) => matchesFilters(n, f) && (needle === "" || n.label.toLowerCase().includes(needle)),
  );
  return {
    domain_id: domain,
    matches: hits.slice(0, limit).map((n) => ({ node: wireNode(n), cluster_id: "" })),
    counts: tally(hits),
    truncated: false,
    truncation_reason: null,
    coverage: COVERAGE,
    filters_applied: { node_type: [], tag: [], environment: [], cloud: [], health: [] },
  };
}

function neighbourhood(domain: string, id: string): Record<string, unknown> | null {
  const s = stateOf(domain);
  const centre = s.nodes.find((n) => n.id === id);
  if (centre === undefined) return null;
  const edges = s.edges.filter((e) => e.source === id || e.target === id);
  const ids = new Set<string>([id, ...edges.flatMap((e) => [e.source, e.target])]);
  return {
    domain_id: domain,
    nodes: s.nodes.filter((n) => ids.has(n.id)).map(wireNode),
    edges: edges.map(wireEdge),
    truncated: false,
    truncation_reason: null,
    next_cursor: null,
    coverage: COVERAGE,
  };
}

function impact(domain: string, nodeId: string, maxDepth: number): Record<string, unknown> | null {
  const s = stateOf(domain);
  if (!s.nodes.some((n) => n.id === nodeId)) return null;
  const seen = new Set<string>([nodeId]);
  let frontier = [nodeId];
  const levels: Record<string, unknown>[] = [];
  for (let depth = 1; depth <= maxDepth && frontier.length > 0; depth += 1) {
    const edgeIds: string[] = [];
    const next: string[] = [];
    for (const e of s.edges) {
      if (!frontier.includes(e.target) || seen.has(e.source)) continue;
      seen.add(e.source);
      next.push(e.source);
      edgeIds.push(e.id);
    }
    // A second edge into an already-reached node still belongs to this level.
    for (const e of s.edges) {
      if (frontier.includes(e.target) && next.includes(e.source) && !edgeIds.includes(e.id)) {
        edgeIds.push(e.id);
      }
    }
    if (next.length === 0) break;
    levels.push({
      depth,
      nodes: next.map((id) => {
        const n = s.nodes.find((x) => x.id === id) as IncidentNode;
        return { id, kind: n.kind, label: n.label, domain_id: domain, health: n.health };
      }),
      edge_ids: edgeIds,
    });
    frontier = next;
  }
  return {
    domain_id: domain,
    node_id: nodeId,
    direction: "dependents",
    levels,
    truncated: false,
    truncation_reason: null,
    coverage: COVERAGE,
  };
}

// ---- control ------------------------------------------------------------------------------

/**
 * Body of the test-only control route. `flip` changes one node's health, `add_node` adds a node
 * to the viewport (with an edge to `depends_on`), `reset` restores the fixture. The route exists
 * only in this mock; the real API has nothing like it.
 */
export type ControlBody =
  | { action: "flip"; node_id: string; health: Health }
  | {
      action: "add_node";
      node_id: string;
      label: string;
      kind?: Kind;
      depends_on?: string;
      environment?: string;
    }
  | { action: "reset" };

/** Applies a control action; returns false for an unknown node or action. */
export function control(domain: string, body: unknown): boolean {
  if (typeof body !== "object" || body === null) return false;
  const b = body as Record<string, unknown>;
  if (b["action"] === "reset") {
    states.delete(domain);
    return true;
  }
  const s = stateOf(domain);
  if (b["action"] === "flip") {
    const target = s.nodes.find((n) => n.id === b["node_id"]);
    const health = b["health"];
    if (
      target === undefined ||
      !["ok", "degraded", "failing", "unknown"].includes(String(health))
    ) {
      return false;
    }
    target.health = health as Health;
    return true;
  }
  if (b["action"] === "add_node") {
    const id = b["node_id"];
    const label = b["label"];
    if (typeof id !== "string" || typeof label !== "string" || s.nodes.some((n) => n.id === id)) {
      return false;
    }
    const kind = (typeof b["kind"] === "string" ? b["kind"] : "agent") as Kind;
    const env = typeof b["environment"] === "string" ? b["environment"] : "production";
    s.nodes.push(node(id, kind, label, env, "commercial", "ok"));
    const dependsOn = b["depends_on"];
    if (typeof dependsOn === "string" && s.nodes.some((n) => n.id === dependsOn)) {
      s.edges.push(edge(id, dependsOn, "observed"));
    }
    return true;
  }
  return false;
}

// ---- dispatch -----------------------------------------------------------------------------

function json(ctx: FeatureMockContext, status: number, body: unknown): void {
  ctx.res.writeHead(status, { "content-type": "application/json", ...ctx.cors });
  ctx.res.end(JSON.stringify(body));
}

function problem(ctx: FeatureMockContext, status: number, code: string, detail: string): void {
  ctx.res.writeHead(status, { "content-type": "application/problem+json", ...ctx.cors });
  ctx.res.end(
    JSON.stringify({
      schema_version: "1.0.0",
      type: `https://neurosphere.invalid/problems/${code.replaceAll("_", "-")}`,
      title: detail,
      status,
      detail,
      instance: ctx.url.pathname,
      code,
      reason: detail,
      retryable: false,
      correlation_id: ctx.correlationId,
    }),
  );
}

async function readJson(ctx: FeatureMockContext): Promise<unknown> {
  try {
    return JSON.parse(await ctx.readBody());
  } catch {
    return null;
  }
}

async function impactRoute(ctx: FeatureMockContext, domain: string): Promise<void> {
  const body = (await readJson(ctx)) as Record<string, unknown> | null;
  const nodeId = body?.["node_id"];
  const depth = body?.["max_depth"];
  if (typeof nodeId !== "string" || nodeId === "") {
    return problem(ctx, 422, "validation_failed", "node_id is required");
  }
  if (typeof depth !== "number" || !Number.isInteger(depth) || depth < 1 || depth > 5) {
    return problem(ctx, 422, "validation_failed", "max_depth must be 1 to 5");
  }
  const result = impact(domain, nodeId, depth);
  if (result === null) return problem(ctx, 404, "not_found", "unknown node");
  json(ctx, 200, result);
}

async function controlRoute(ctx: FeatureMockContext, domain: string): Promise<void> {
  const body = await readJson(ctx);
  if (!control(domain, body)) return problem(ctx, 422, "validation_failed", "bad control body");
  json(ctx, 200, { ok: true });
}

/** Answers the map routes of the incident fixture family; false (pass) for everything else. */
export const handle: FeatureMockHandler = (ctx) => {
  const path = ctx.url?.pathname;
  if (path === undefined) return false;
  const method = ctx.req.method ?? "GET";
  const neighbour = NEIGHBORHOOD.exec(path);
  const root = MAP_ROOT.exec(path);
  const match = neighbour ?? root;
  if (match === null) return false;
  const domain = decodeURIComponent(match[1] ?? "");
  if (!DOMAIN_FAMILY.test(domain)) return false;
  if (!ctx.authorized) {
    json(ctx, 401, { error: "missing or unrecognised token" });
    return true;
  }
  if (neighbour !== null) {
    if (method !== "GET") return false;
    const id = neighbour[2]?.split("/").map(decodeURIComponent).join("/") ?? "";
    const result = neighbourhood(domain, id);
    if (result === null) problem(ctx, 404, "not_found", "unknown node");
    else json(ctx, 200, result);
    return true;
  }
  const route = root?.[2];
  if (route === "viewport" && method === "GET") json(ctx, 200, viewport(domain, ctx.url));
  else if (route === "search" && method === "GET") json(ctx, 200, search(domain, ctx.url));
  else if (route === "impact" && method === "POST") void impactRoute(ctx, domain);
  else if (route === "__e2e/control" && method === "POST") void controlRoute(ctx, domain);
  else return false;
  return true;
};
