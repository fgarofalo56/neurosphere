import type { FeatureMockContext, FeatureMockHandler } from "./context.ts";

/**
 * PRP-31 item 4 mock: relationship curation. Shapes follow `PresentedEdge`, `OverrideHistory`,
 * `Page[EdgeObservation]` and the Item 2 decision adapter; every id and name is SYNTHETIC.
 *
 * The mock only imitates the outcomes the real API owns, keyed on the persona in the fake token:
 *   - GET edge / overrides: any signed-in persona (data.read);
 *   - GET observations: Auditor or Admin (evidence.read), 403 otherwise;
 *   - POST decision: Steward or Admin (catalog.curate), 403 otherwise. The body is checked
 *     strictly: a key outside the Item 2 request model is a 422, like the adapter's extra=forbid.
 *     A stale version/etag is 409 `stale_edge`; an edge id containing "stale-edge" is always stale.
 * The UI never decides: it reflects whatever this mock answers.
 */

const EDGES_PREFIX = "/api/v1/catalog/curation/edges/";
const DOMAINS_PREFIX = "/api/v1/catalog/domains/";
const DOMAIN_OK = "commercial:e2e:sandbox:domain:finance";
const CURATE_ROLES = new Set(["steward", "admin"]);
const EVIDENCE_ROLES = new Set(["auditor", "admin"]);
const DECISIONS = new Set(["accept", "reject", "override", "lock", "unlock"]);
const ALLOWED_KEYS = new Set([
  "decision",
  "reason",
  "expected_edge_version",
  "expected_edge_etag",
  "lock_expiry",
  "set_confidence",
  "set_validity",
]);

interface MockLock {
  locked: boolean;
  reason: string | null;
  expiry: string | null;
  actor: string | null;
}

interface MockOverride {
  id: string;
  decision: string;
  actor: string;
  reason: string;
  decided_at: string;
  lock: MockLock | null;
  set_confidence: number | null;
}

interface MockEdge {
  edge_id: string;
  version: number;
  status: "asserted" | "inferred" | "curated";
  hidden: boolean;
  confidence: number;
  lock: MockLock;
  overrides: MockOverride[];
}

const edges = new Map<string, MockEdge>();
const MOCK_ACTOR = "commercial:e2e:entra:person:psn_mock_steward";

function edgeFor(edgeId: string): MockEdge {
  let edge = edges.get(edgeId);
  if (edge === undefined) {
    edge = {
      edge_id: edgeId,
      version: 3,
      status: "inferred",
      hidden: false,
      confidence: 0.62,
      lock: { locked: false, reason: null, expiry: null, actor: null },
      overrides: [],
    };
    edges.set(edgeId, edge);
  }
  return edge;
}

function etagOf(edge: MockEdge): string {
  return `etag-${edge.version}`;
}

function presented(edge: MockEdge): Record<string, unknown> {
  const last = edge.overrides.at(-1);
  return {
    edge_id: edge.edge_id,
    relation_type: "uses_model",
    source_id: "commercial:e2e:sandbox:agent:sample-agent",
    target_id: "commercial:e2e:sandbox:model_deployment:sample-model",
    domain_id: DOMAIN_OK,
    hidden: edge.hidden,
    status: edge.status,
    confidence: edge.confidence,
    validity: { valid_from: "2026-09-01T00:00:00Z", valid_to: null },
    lock: edge.lock,
    curation:
      last === undefined
        ? null
        : {
            decision: last.decision,
            decided_by: last.actor,
            decided_at: last.decided_at,
            reason: last.reason,
          },
    evidence_ids: [
      "commercial:e2e:sandbox:evidence:obs-1",
      "commercial:e2e:sandbox:evidence:obs-2",
    ],
    security_evidence_ids: ["commercial:e2e:sandbox:evidence:sec-1"],
    first_observed: "2026-09-02T08:00:00Z",
    last_observed: "2026-10-20T08:00:00Z",
    pinned: edge.lock.locked,
    override_ids: edge.overrides.map((o) => o.id),
    version: edge.version,
    etag: etagOf(edge),
    provenance: {
      method: "trace_observation",
      source_id: "sandbox-connector",
      recorded_at: "2026-10-20T08:00:00Z",
    },
  };
}

function observationPage(cursor: string | null): Record<string, unknown> {
  const observation = (n: number): Record<string, unknown> => ({
    id: `commercial:e2e:sandbox:evidence:obs-${n}`,
    observed_at: `2026-10-${String(10 + n).padStart(2, "0")}T08:00:00Z`,
    confidence: 0.6 + n / 100,
    provenance: {
      method: "trace_observation",
      source_id: "sandbox-connector",
      recorded_at: "2026-10-20T08:00:00Z",
    },
    evidence_ids: [`commercial:e2e:sandbox:evidence:obs-${n}`],
    security_evidence_ids: n === 1 ? ["commercial:e2e:sandbox:evidence:sec-1"] : [],
  });
  return cursor === null
    ? { items: [observation(1), observation(2)], next_cursor: "cursor-2" }
    : { items: [observation(3)], next_cursor: null };
}

function json(ctx: FeatureMockContext, status: number, body: unknown): true {
  ctx.res.writeHead(status, { "content-type": "application/json", ...ctx.cors });
  ctx.res.end(JSON.stringify(body));
  return true;
}

function isFutureTimestamp(value: unknown): boolean {
  return typeof value === "string" && new Date(value).getTime() > Date.now();
}

async function decide(ctx: FeatureMockContext, edge: MockEdge): Promise<void> {
  if (ctx.role === undefined || !CURATE_ROLES.has(ctx.role)) {
    ctx.forbidden();
    return;
  }
  let body: Record<string, unknown>;
  try {
    const parsed: unknown = JSON.parse(await ctx.readBody());
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) throw new Error();
    body = parsed as Record<string, unknown>;
  } catch {
    ctx.problem(422, "invalid_schema", "invalid_body", "The body is not a JSON object.");
    return;
  }
  const extra = Object.keys(body).filter((key) => !ALLOWED_KEYS.has(key));
  const decision = body["decision"];
  const reason = body["reason"];
  if (
    extra.length > 0 ||
    typeof decision !== "string" ||
    !DECISIONS.has(decision) ||
    typeof reason !== "string" ||
    reason === "" ||
    typeof body["expected_edge_version"] !== "number" ||
    typeof body["expected_edge_etag"] !== "string"
  ) {
    ctx.problem(422, "invalid_schema", "extra_forbidden", "The decision body is not valid.");
    return;
  }
  if (
    edge.edge_id.includes("stale-edge") ||
    body["expected_edge_version"] !== edge.version ||
    body["expected_edge_etag"] !== etagOf(edge)
  ) {
    ctx.problem(409, "stale_version", "stale_edge", "The edge changed since it was read.");
    return;
  }
  const pinning = decision === "lock" || decision === "override";
  if (pinning && body["lock_expiry"] === undefined) {
    ctx.problem(422, "invalid_schema", "lock_requires_reason_and_expiry", "Expiry is required.");
    return;
  }
  if (pinning && !isFutureTimestamp(body["lock_expiry"])) {
    ctx.problem(
      422,
      "invalid_schema",
      "lock_expiry_not_in_future",
      "Expiry must be in the future.",
    );
    return;
  }
  if (!pinning && (body["lock_expiry"] !== undefined || body["set_confidence"] !== undefined)) {
    ctx.problem(422, "invalid_schema", "lock_not_allowed", "Pinning applies to lock and override.");
    return;
  }
  const lock: MockLock | null = pinning
    ? {
        locked: true,
        reason,
        expiry: body["lock_expiry"] as string,
        actor: MOCK_ACTOR,
      }
    : null;
  if (decision === "unlock") {
    edge.lock = { locked: false, reason: null, expiry: null, actor: null };
  } else if (lock !== null) {
    edge.lock = lock;
  }
  if (typeof body["set_confidence"] === "number") edge.confidence = body["set_confidence"];
  edge.status = "curated";
  edge.hidden = decision === "reject";
  edge.version += 1;
  const record: MockOverride = {
    id: `commercial:e2e:sandbox:edge_override:ov-${edge.version}`,
    decision,
    actor: MOCK_ACTOR,
    reason,
    decided_at: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
    lock,
    set_confidence: typeof body["set_confidence"] === "number" ? body["set_confidence"] : null,
  };
  edge.overrides.push(record);
  json(ctx, 201, { override: record, presented: presented(edge) });
}

export const handle: FeatureMockHandler = (ctx) => {
  // The shared registry test calls every handler with an empty context; that must pass through.
  const url = (ctx as Partial<FeatureMockContext>).url;
  if (url === undefined) return false;
  const path = url.pathname;
  const isEdgeRead = path.startsWith(EDGES_PREFIX) && ctx.req.method === "GET";
  const isDecision =
    path.startsWith(DOMAINS_PREFIX) &&
    path.includes("/curation/edges/") &&
    path.endsWith("/decisions") &&
    ctx.req.method === "POST";
  if (!isEdgeRead && !isDecision) return false;
  if (!ctx.authorized) return json(ctx, 401, { error: "missing or unrecognised token" });

  if (isDecision) {
    const start = path.indexOf("/curation/edges/") + "/curation/edges/".length;
    const encoded = path.slice(start, path.length - "/decisions".length);
    void decide(ctx, edgeFor(decodeURIComponent(encoded)));
    return true;
  }

  const rest = path.slice(EDGES_PREFIX.length);
  if (rest.endsWith("/overrides")) {
    const id = decodeURIComponent(rest.slice(0, rest.length - "/overrides".length));
    const edge = edgeFor(id);
    return json(ctx, 200, { edge_id: id, overrides: edge.overrides });
  }
  if (rest.endsWith("/observations")) {
    if (ctx.role === undefined || !EVIDENCE_ROLES.has(ctx.role)) {
      ctx.forbidden();
      return true;
    }
    return json(ctx, 200, observationPage(url.searchParams.get("cursor")));
  }
  return json(ctx, 200, presented(edgeFor(decodeURIComponent(rest))));
};
