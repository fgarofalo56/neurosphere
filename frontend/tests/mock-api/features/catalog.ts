import type { FeatureMockContext, FeatureMockHandler } from "./context.ts";

/**
 * PRP-31 item 3: catalog explorer mock (SYNTHETIC data only). It imitates the outcomes the real
 * API owns, from services/api/neurosphere_api/catalog/ and ui_adapters/catalog.py:
 *
 * - the domain-path adapters answer only for the Finance sandbox domain (anything else is 403);
 * - the list is clamped to 4 per page so "N+" and cursor paging are exercised;
 * - deprecate / recertify / stale-agent confirm / export need the `admin` or `steward` persona
 *   (stand-ins for catalog.curate / data.export); reads work for any authorized caller;
 * - deprecate and recertify need an If-Match that equals the stored ETag, else 409 stale_version;
 *   the owner "contested-team" is always changed by someone else first, so its first recertify
 *   attempt is a deterministic 409 and the ETag the page reloads is the new one.
 */

const DOMAIN = "commercial:e2e:sandbox:domain:finance";
const PREFIX = "commercial:e2e:catalog:";
const NOW = "2026-10-20T12:00:00Z";
const MAX_PAGE = 4;

type Lifecycle = "draft" | "active" | "deprecated" | "retired";

interface Entity {
  id: string;
  entity_type: string;
  domain_id: string;
  display_name: string;
  lifecycle_status: Lifecycle;
  version: number;
  etag: string;
  updated_at: string;
  owner_kind?: string;
  recertified_at?: string | null;
  recertify_by?: string;
}

interface Edge {
  edge_id: string;
  relation_type: string;
  source_id: string;
  target_id: string;
  domain_id: string;
  status: "asserted" | "inferred" | "curated";
  confidence: number;
}

const AGENT = `${PREFIX}agent:sample-agent`;
const MODEL = `${PREFIX}model_deployment:sample-model`;
const OWNER = `${PREFIX}owner:finance-team`;
const CONTESTED = `${PREFIX}owner:contested-team`;
const IDLE_ONE = `${PREFIX}agent:idle-agent-one`;
const IDLE_TWO = `${PREFIX}agent:idle-agent-two`;
const EDGE_USES = "commercial:e2e:edge:sample-agent/uses/sample-model";
const EDGE_OWNED = "commercial:e2e:edge:sample-agent:owned_by:finance-team";

function entity(id: string, type: string, name: string, extra: Partial<Entity> = {}): Entity {
  return {
    id,
    entity_type: type,
    domain_id: DOMAIN,
    display_name: name,
    lifecycle_status: "active",
    version: 1,
    etag: `etag-${name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-1`,
    updated_at: NOW,
    ...extra,
  };
}

function seed(): Entity[] {
  return [
    entity(AGENT, "agent", "Sample agent"),
    entity(MODEL, "model_deployment", "Sample model"),
    entity(OWNER, "owner", "Finance team", {
      owner_kind: "team",
      recertified_at: "2026-07-01T00:00:00Z",
      recertify_by: "2026-11-05T00:00:00Z",
    }),
    entity(CONTESTED, "owner", "Contested team", {
      owner_kind: "team",
      recertified_at: null,
      recertify_by: "2026-10-01T00:00:00Z",
    }),
    entity(IDLE_ONE, "agent", "Idle agent one"),
    entity(IDLE_TWO, "agent", "Idle agent two"),
    entity(`${PREFIX}tool:legacy-tool`, "tool", "Legacy tool", { lifecycle_status: "deprecated" }),
    entity(`${PREFIX}service:ledger`, "service", "Ledger service", { lifecycle_status: "draft" }),
    entity(`${PREFIX}tool:report-writer`, "tool", "Report writer"),
    entity(`${PREFIX}agent:budget-bot`, "agent", "Budget bot"),
  ];
}

const edges: readonly Edge[] = [
  {
    edge_id: EDGE_USES,
    relation_type: "uses_model",
    source_id: AGENT,
    target_id: MODEL,
    domain_id: DOMAIN,
    status: "asserted",
    confidence: 0.92,
  },
  {
    edge_id: EDGE_OWNED,
    relation_type: "owned_by",
    source_id: AGENT,
    target_id: OWNER,
    domain_id: DOMAIN,
    status: "curated",
    confidence: 1,
  },
];

let entities = seed();
let contestedHit = false;
let counter = 1;

function bump(e: Entity, patch: Partial<Entity>): Entity {
  counter += 1;
  Object.assign(e, patch, {
    version: e.version + 1,
    etag: `etag-${String(counter)}`,
    updated_at: NOW,
  });
  return e;
}

function send(ctx: FeatureMockContext, status: number, body: unknown): void {
  ctx.res.writeHead(status, { "content-type": "application/json", ...ctx.cors });
  ctx.res.end(JSON.stringify(body));
}

function canChange(ctx: FeatureMockContext): boolean {
  return ctx.role === "admin" || ctx.role === "steward";
}

function parse(raw: string): Record<string, unknown> {
  try {
    const value: unknown = JSON.parse(raw === "" ? "{}" : raw);
    return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

function graph(nodes: Entity[], used: Edge[], paths: unknown[] = [], truncated = false) {
  return {
    nodes,
    edges: used,
    paths,
    truncated,
    truncated_reason: truncated ? "max_nodes" : null,
    visited_nodes: nodes.length,
    visited_edges: used.length,
  };
}

function byId(id: string): Entity | undefined {
  return entities.find((e) => e.id === id);
}

function listFrom(ctx: FeatureMockContext, pool: Entity[], limit: number) {
  const offset = Number(ctx.url.searchParams.get("cursor") ?? "0") || 0;
  const size = Math.min(
    Number(ctx.url.searchParams.get("page_size") ?? limit) || limit,
    MAX_PAGE * 25,
  );
  const effective = Math.min(size, limit);
  const items = pool.slice(offset, offset + effective);
  const next = offset + effective < pool.length ? String(offset + effective) : null;
  return { items, next };
}

function filtered(ctx: FeatureMockContext): Entity[] {
  const types = ctx.url.searchParams.getAll("entity_type");
  const lifecycles = ctx.url.searchParams.getAll("lifecycle");
  return entities.filter(
    (e) =>
      (types.length === 0 || types.includes(e.entity_type)) &&
      (lifecycles.length === 0 || lifecycles.includes(e.lifecycle_status)),
  );
}

async function domainRoute(ctx: FeatureMockContext, domain: string, op: string): Promise<void> {
  if (domain !== DOMAIN) {
    ctx.forbidden();
    return;
  }
  if (op === "entities" && ctx.req.method === "GET") {
    const { items, next } = listFrom(ctx, filtered(ctx), MAX_PAGE);
    send(ctx, 200, { items, next_cursor: next });
    return;
  }
  if (op === "search" && ctx.req.method === "POST") {
    const body = parse(await ctx.readBody());
    const term = typeof body["term"] === "string" ? body["term"].toLowerCase() : "";
    const types = Array.isArray(body["entity_types"]) ? (body["entity_types"] as string[]) : [];
    const nodes = entities.filter(
      (e) =>
        (term === "" || e.display_name.toLowerCase().includes(term) || e.id.includes(term)) &&
        (types.length === 0 || types.includes(e.entity_type)),
    );
    send(ctx, 200, graph(nodes, []));
    return;
  }
  if (op === "export" && ctx.req.method === "GET") {
    if (ctx.role !== "admin") {
      ctx.forbidden();
      return;
    }
    const { items, next } = listFrom(ctx, filtered(ctx), 5);
    send(ctx, 200, { exported_at: NOW, domains: [DOMAIN], items, next_cursor: next });
    return;
  }
  send(ctx, 404, { error: "not found" });
}

function lineage(ctx: FeatureMockContext, kind: string, body: Record<string, unknown>): void {
  const nodeId = typeof body["node_id"] === "string" ? body["node_id"] : "";
  const self = byId(nodeId);
  if (self === undefined) {
    send(ctx, 404, { error: "not found" });
    return;
  }
  const out = edges.filter((e) => e.source_id === nodeId);
  const into = edges.filter((e) => e.target_id === nodeId);
  if (kind === "neighbors") {
    const used = [...out, ...into];
    const ids = new Set(used.flatMap((e) => [e.source_id, e.target_id]));
    send(
      ctx,
      200,
      graph(
        entities.filter((e) => ids.has(e.id)),
        used,
      ),
    );
    return;
  }
  const down = body["direction"] !== "upstream";
  const used = down ? out : into;
  const paths = used.map((e) => ({
    node_ids: [e.source_id, e.target_id],
    edge_ids: [e.edge_id],
  }));
  const ids = new Set([nodeId, ...used.flatMap((e) => [e.source_id, e.target_id])]);
  send(
    ctx,
    200,
    graph(
      entities.filter((e) => ids.has(e.id)),
      used,
      paths,
      down && used.length > 1,
    ),
  );
}

function change(ctx: FeatureMockContext, id: string, op: string, body: Record<string, unknown>) {
  const target = byId(id);
  if (target === undefined) {
    send(ctx, 404, { error: "not found" });
    return;
  }
  if (!canChange(ctx)) {
    ctx.forbidden();
    return;
  }
  const ifMatch = (ctx.req.headers["if-match"] ?? "")
    .toString()
    .replace(/^W\//, "")
    .replace(/"/g, "");
  if (id === CONTESTED && !contestedHit) {
    contestedHit = true;
    bump(target, {});
  }
  if (ifMatch !== target.etag) {
    ctx.problem(409, "stale_version", "stale_version", "The entity changed since it was read.");
    return;
  }
  if (op === "deprecate") {
    send(ctx, 200, bump(target, { lifecycle_status: "deprecated" }));
    return;
  }
  const days = body["valid_for_days"];
  if (typeof days !== "number" || days < 1 || days > 730) {
    ctx.problem(422, "invalid_schema", undefined, "valid_for_days must be 1 to 730.");
    return;
  }
  const by = new Date(Date.parse(NOW) + days * 86_400_000).toISOString().replace(".000Z", "Z");
  // The next attempt on the contested owner is again overtaken by "someone else" (repeatable runs).
  if (id === CONTESTED) contestedHit = false;
  send(ctx, 200, bump(target, { recertified_at: NOW, recertify_by: by }));
}

function recertifications(ctx: FeatureMockContext): void {
  const include = ctx.url.searchParams.get("include") ?? "both";
  const items = [
    {
      owner_id: CONTESTED,
      domain_id: DOMAIN,
      owner_kind: "team",
      recertified_at: null,
      recertify_by: "2026-10-01T00:00:00Z",
      state: "overdue",
      days_until_due: -19,
    },
    {
      owner_id: OWNER,
      domain_id: DOMAIN,
      owner_kind: "team",
      recertified_at: "2026-07-01T00:00:00Z",
      recertify_by: "2026-11-05T00:00:00Z",
      state: "due",
      days_until_due: 16,
    },
  ].filter((i) => include === "both" || i.state === include);
  send(ctx, 200, { items, scanned: 2, next_cursor: null });
}

function stalePlan(windowDays: number) {
  return {
    plan_id: "plan-e2e-0001",
    as_of: NOW,
    window_days: windowDays,
    candidates: [IDLE_ONE, IDLE_TWO].map((id) => ({
      agent_id: id,
      etag: byId(id)?.etag ?? "etag-missing",
      domain_id: DOMAIN,
      last_observed: "2026-06-01T00:00:00Z",
    })),
    truncated: false,
  };
}

async function reconcile(ctx: FeatureMockContext, op: string): Promise<void> {
  const body = parse(await ctx.readBody());
  if (op === "dry-run") {
    const days = body["window_days"];
    if (typeof days !== "number" || days < 1 || days > 3650) {
      ctx.problem(422, "invalid_schema", undefined, "window_days must be 1 to 3650.");
      return;
    }
    send(ctx, 200, stalePlan(days));
    return;
  }
  if (!canChange(ctx)) {
    ctx.forbidden();
    return;
  }
  if (body["plan_id"] !== "plan-e2e-0001" || !Array.isArray(body["candidates"])) {
    ctx.problem(409, "stale_version", "plan_mismatch", "The plan no longer matches.");
    return;
  }
  const items = (body["candidates"] as { agent_id: string }[]).map((c, i) =>
    i === 1
      ? { agent_id: c.agent_id, status: "failed", code: "stale_version", etag: null }
      : { agent_id: c.agent_id, status: "marked", code: null, etag: `etag-marked-${String(i)}` },
  );
  send(ctx, 200, { plan_id: "plan-e2e-0001", items });
}

export const handle: FeatureMockHandler = (ctx) => {
  // The registry test calls every handler with an empty object: nothing to answer then.
  const url = (ctx as { url?: URL }).url;
  if (url === undefined) return false;
  const rest = /^\/api\/v1\/catalog\/(.+)$/.exec(url.pathname)?.[1];
  if (rest === undefined) return false;
  const method = ctx.req.method ?? "GET";

  const domainMatch = /^domains\/([^/]+)\/(entities|search|export)$/.exec(rest);
  const entityMatch = /^entities\/([^/]+?)(?:\/(deprecate|recertify))?$/.exec(rest);
  const lineageMatch = /^lineage\/(neighbors|impact)$/.exec(rest);
  const reconcileMatch = /^reconcile\/stale-agents\/(dry-run|confirm)$/.exec(rest);
  const isRecerts = rest === "recertifications" && method === "GET";
  const isEntityGet = entityMatch !== null && entityMatch[2] === undefined && method === "GET";
  const isEntityChange = entityMatch !== null && entityMatch[2] !== undefined && method === "POST";
  const mine =
    domainMatch !== null ||
    isEntityGet ||
    isEntityChange ||
    (lineageMatch !== null && method === "POST") ||
    (reconcileMatch !== null && method === "POST") ||
    isRecerts;
  if (!mine) return false;

  if (!ctx.authorized) {
    send(ctx, 401, { error: "missing or unrecognised token" });
    return true;
  }
  if (domainMatch !== null) {
    void domainRoute(ctx, decodeURIComponent(domainMatch[1] ?? ""), domainMatch[2] ?? "");
  } else if (isEntityGet && entityMatch !== null) {
    const found = byId(decodeURIComponent(entityMatch[1] ?? ""));
    if (found === undefined) send(ctx, 404, { error: "not found" });
    else send(ctx, 200, found);
  } else if (isEntityChange && entityMatch !== null) {
    const id = decodeURIComponent(entityMatch[1] ?? "");
    const op = entityMatch[2] ?? "";
    void ctx.readBody().then((raw) => change(ctx, id, op, parse(raw)));
  } else if (lineageMatch !== null) {
    void ctx.readBody().then((raw) => lineage(ctx, lineageMatch[1] ?? "", parse(raw)));
  } else if (reconcileMatch !== null) {
    void reconcile(ctx, reconcileMatch[1] ?? "");
  } else if (isRecerts) {
    recertifications(ctx);
  }
  return true;
};

/** Test hook: restores the seed so repeated runs against one server start from a known state. */
export function resetCatalogMock(): void {
  entities = seed();
  contestedHit = false;
  counter = 1;
}
