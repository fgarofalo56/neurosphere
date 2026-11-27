import type { FeatureMockContext, FeatureMockHandler } from "./context.ts";

/**
 * PRP-107 item 7 mock: notification channels, subscriptions and the delivery list, following the
 * `/api/v1/admin/notifications` contract. In-memory state; a spec that changes it calls
 * `resetNotifications()`. Every id, host and Key Vault reference is SYNTHETIC; no secret value
 * exists in this module, and a write whose credential is not a Key Vault reference is refused.
 *
 * Persona gate (a stand-in for the API's customer-level `config.manage` check): `admin` only; any
 * other persona gets a 403 problem. Writes follow the admin rules: `If-Match` is required on PUT
 * and DELETE (428 without, 412 on a mismatch). Refusal fixtures:
 * - kind `email` is `not_built`: create answers 409 `channel_kind_not_built`;
 * - allowed host `blocked.example.net` answers 422 `host_not_allowed`, `gov-only.example.net` 422
 *   `cloud_boundary`;
 * - the channel `flaky-hook` answers a failed test send (HTTP 500).
 */

export const NOTIFICATIONS_API = "/api/v1/admin/notifications";
export const NOTIFICATION_CHANNEL_ID = "ops-webhook";
export const NOTIFICATION_TEAMS_CHANNEL_ID = "ops-teams";
export const NOTIFICATION_FLAKY_CHANNEL_ID = "flaky-hook";
export const NOTIFICATION_SUBSCRIPTION_ID = "ops-hitl";
export const NOTIFICATION_BLOCKED_HOST = "blocked.example.net";
export const NOTIFICATION_CROSS_CLOUD_HOST = "gov-only.example.net";

const STAMP = "2026-11-26T09:00:00Z";
const DOMAIN = "commercial:e2e:sandbox:domain:finance";
const VAULT =
  /^https:\/\/[a-z][a-z0-9-]{1,22}[a-z0-9]\.vault\.(azure\.net|usgovcloudapi\.net)\/secrets\/[A-Za-z0-9-]{1,127}(\/[0-9a-f]{32})?$/;
const STATUSES = ["pending", "sending", "delivered", "failed", "dead_lettered", "suppressed"];

type Doc = Record<string, unknown>;
interface Stored {
  doc: Doc;
  version: number;
}

function ref(name: string): Doc {
  return { kind: "key_vault_secret", secret_uri: `https://kv-e2e.vault.azure.net/secrets/${name}` };
}

function channel(id: string, over: Doc = {}): Doc {
  return {
    schema_version: "1.0.0",
    channel_id: id,
    cloud: "commercial",
    customer_id: "e2e",
    domain_id: DOMAIN,
    display_name: id,
    kind: "webhook",
    allowed_host: "hooks.example.org",
    endpoint_credential: ref(`${id}-endpoint`),
    hmac_credential: ref(`${id}-signing`),
    local_sink: false,
    local_sink_url: null,
    enabled: true,
    ...over,
  };
}

function subscription(id: string, channelId: string, over: Doc = {}): Doc {
  return {
    schema_version: "1.0.0",
    subscription_id: id,
    cloud: "commercial",
    customer_id: "e2e",
    domain_id: DOMAIN,
    channel_id: channelId,
    event_classes: ["hitl_item_assigned", "hitl_item_escalated"],
    audience_roles: ["domain_steward"],
    min_severity: "medium",
    enabled: true,
    ...over,
  };
}

function delivery(n: number, channelId: string, status: string, over: Doc = {}): Doc {
  return {
    schema_version: "1.0.0",
    notification_id: `00000000-0000-4000-8000-00000000000${n}`,
    cloud: "commercial",
    customer_id: "e2e",
    domain_id: DOMAIN,
    channel_id: channelId,
    subscription_id: NOTIFICATION_SUBSCRIPTION_ID,
    event_class: "hitl_item_assigned",
    severity: "medium",
    title: `Review item ${n} assigned`,
    link: `/review/${n}`,
    status,
    attempts: status === "pending" ? 0 : 1,
    next_attempt_at: null,
    last_error_code: status === "delivered" ? "http_200" : status === "failed" ? "http_500" : null,
    created_at: STAMP,
    delivered_at: status === "delivered" ? STAMP : null,
    ...over,
  };
}

function initial(): { channels: Stored[]; subs: Stored[]; deliveries: Doc[] } {
  return {
    channels: [
      { doc: channel(NOTIFICATION_CHANNEL_ID, { display_name: "Ops webhook" }), version: 1 },
      {
        doc: channel(NOTIFICATION_TEAMS_CHANNEL_ID, {
          display_name: "Ops Teams",
          kind: "teams_webhook",
          allowed_host: "prod-00.westus.logic.azure.com",
          hmac_credential: null,
          enabled: false,
        }),
        version: 1,
      },
      { doc: channel(NOTIFICATION_FLAKY_CHANNEL_ID, { display_name: "Flaky hook" }), version: 1 },
    ],
    subs: [
      {
        doc: subscription(NOTIFICATION_SUBSCRIPTION_ID, NOTIFICATION_CHANNEL_ID),
        version: 1,
      },
    ],
    deliveries: [
      delivery(1, NOTIFICATION_CHANNEL_ID, "delivered"),
      delivery(2, NOTIFICATION_CHANNEL_ID, "delivered"),
      delivery(3, NOTIFICATION_FLAKY_CHANNEL_ID, "failed"),
      delivery(4, NOTIFICATION_CHANNEL_ID, "pending"),
    ],
  };
}

let state = initial();

export function resetNotifications(): void {
  state = initial();
}

function json(
  ctx: FeatureMockContext,
  status: number,
  body: unknown,
  extra: Record<string, string> = {},
  type = "application/json",
): void {
  ctx.res.writeHead(status, { "content-type": type, ...ctx.cors, ...extra });
  ctx.res.end(body === undefined ? "" : JSON.stringify(body));
}

function problem(
  ctx: FeatureMockContext,
  status: number,
  code: string,
  detail: string,
  reason: string = code,
): void {
  json(
    ctx,
    status,
    {
      schema_version: "1.0.0",
      type: `https://neurosphere.invalid/problems/${code.replaceAll("_", "-")}`,
      title: detail,
      status,
      detail,
      instance: ctx.url.pathname,
      code,
      reason,
      retryable: false,
      correlation_id: ctx.correlationId,
    },
    {},
    "application/problem+json",
  );
}

async function readJson(ctx: FeatureMockContext): Promise<Doc> {
  try {
    const parsed: unknown = JSON.parse(await ctx.readBody());
    return typeof parsed === "object" && parsed !== null ? (parsed as Doc) : {};
  } catch {
    return {};
  }
}

const etagOf = (prefix: string, version: number): string => `"${prefix}-${version}"`;
const trail = (rest: string): string[] =>
  rest
    .split("/")
    .filter((p) => p !== "")
    .map(decodeURIComponent);

function counts(channelId: string): Record<string, number> {
  const out: Record<string, number> = Object.fromEntries(STATUSES.map((s) => [s, 0]));
  for (const d of state.deliveries) {
    if (d["channel_id"] === channelId)
      out[String(d["status"])] = (out[String(d["status"])] ?? 0) + 1;
  }
  return out;
}

function channelView(s: Stored): Doc {
  const id = String(s.doc["channel_id"]);
  const failed = state.deliveries.find((d) => d["channel_id"] === id && d["status"] === "failed");
  return {
    channel: s.doc,
    version: s.version,
    etag: etagOf("channel", s.version),
    updated_at: STAMP,
    updated_by: "psn-mock-admin",
    delivery_counts: counts(id),
    last_error_code: failed === undefined ? null : (failed["last_error_code"] as string),
  };
}

function subscriptionView(s: Stored): Doc {
  return {
    subscription: s.doc,
    version: s.version,
    etag: etagOf("subscription", s.version),
    updated_at: STAMP,
    updated_by: "psn-mock-admin",
  };
}

/** The refusal an egress guard or the kind registry would give for this channel body, if any. */
function channelRefusal(body: Doc): { status: number; code: string } | undefined {
  if (body["kind"] === "email") return { status: 409, code: "channel_kind_not_built" };
  for (const field of ["endpoint_credential", "hmac_credential"]) {
    const cred = body[field];
    if (cred === null || cred === undefined) continue;
    const uri = (cred as Doc)["secret_uri"];
    if (
      (cred as Doc)["kind"] !== "key_vault_secret" ||
      typeof uri !== "string" ||
      !VAULT.test(uri)
    ) {
      return { status: 422, code: "invalid_credential_reference" };
    }
  }
  if (body["allowed_host"] === NOTIFICATION_BLOCKED_HOST) {
    return { status: 422, code: "host_not_allowed" };
  }
  if (body["allowed_host"] === NOTIFICATION_CROSS_CLOUD_HOST) {
    return { status: 422, code: "cloud_boundary" };
  }
  return undefined;
}

/** A refusal as the real API sends it: the taxonomy code, with the specific reason beside it. */
function refuse(ctx: FeatureMockContext, refusal: { status: number; code: string }): void {
  const taxonomy = refusal.status === 409 ? "capability_unavailable" : "invalid_schema";
  problem(ctx, refusal.status, taxonomy, refusal.code, refusal.code);
}

function ifMatchFailure(ctx: FeatureMockContext, current: string): boolean {
  const header = ctx.req.headers["if-match"];
  if (header === undefined) {
    problem(ctx, 422, "invalid_schema", "If-Match is required", "precondition_required");
    return true;
  }
  if (header !== current) {
    problem(ctx, 409, "stale_version", "etag_mismatch");
    return true;
  }
  return false;
}

interface Collection {
  readonly items: Stored[];
  readonly idField: string;
  readonly prefix: string;
  readonly view: (s: Stored) => Doc;
  readonly set: (next: Stored[]) => void;
  readonly refuse: (body: Doc) => { status: number; code: string } | undefined;
}

async function crud(ctx: FeatureMockContext, c: Collection, parts: string[]): Promise<void> {
  const method = ctx.req.method ?? "GET";
  if (parts.length === 0) {
    if (method === "GET") return json(ctx, 200, { items: c.items.map(c.view) });
    if (method !== "POST") return json(ctx, 405, { error: "method not allowed" });
    const body = await readJson(ctx);
    const refusal = c.refuse(body);
    if (refusal !== undefined) {
      return refuse(ctx, refusal);
    }
    const id = String(body[c.idField] ?? "");
    if (!/^[a-z0-9][a-z0-9._-]{0,63}$/.test(id)) {
      return problem(ctx, 422, "invalid_schema", `${c.idField} does not match the allowed pattern`);
    }
    if (c.items.some((s) => s.doc[c.idField] === id)) {
      return problem(ctx, 409, "conflict", `${c.idField}_exists`);
    }
    const created = { doc: body, version: 1 };
    c.set([...c.items, created]);
    return json(ctx, 201, c.view(created), { etag: etagOf(c.prefix, 1) });
  }
  const found = c.items.find((s) => s.doc[c.idField] === parts[0]);
  if (found === undefined) return problem(ctx, 404, "not_found", `${c.prefix}_not_found`);
  if (parts.length > 1) return problem(ctx, 404, "not_found", "unknown_route");
  const current = etagOf(c.prefix, found.version);
  if (method === "GET") return json(ctx, 200, c.view(found), { etag: current });
  if (method !== "PUT" && method !== "DELETE")
    return json(ctx, 405, { error: "method not allowed" });
  if (ifMatchFailure(ctx, current)) return;
  if (method === "DELETE") {
    c.set(c.items.filter((s) => s !== found));
    ctx.res.writeHead(204, ctx.cors);
    ctx.res.end();
    return;
  }
  const body = await readJson(ctx);
  const refusal = c.refuse(body);
  if (refusal !== undefined) return refuse(ctx, refusal);
  const next = { doc: { ...body, [c.idField]: found.doc[c.idField] }, version: found.version + 1 };
  c.set(c.items.map((s) => (s === found ? next : s)));
  return json(ctx, 200, c.view(next), { etag: etagOf(c.prefix, next.version) });
}

function subscriptionRefusal(body: Doc): { status: number; code: string } | undefined {
  const known = state.channels.some((c) => c.doc["channel_id"] === body["channel_id"]);
  return known ? undefined : { status: 422, code: "unknown_channel" };
}

async function route(ctx: FeatureMockContext, rest: string): Promise<void> {
  const method = ctx.req.method ?? "GET";
  const parts = trail(rest);
  const head = parts[0];
  if (head === "channel-kinds" && parts.length === 1) {
    if (method !== "GET") return json(ctx, 405, { error: "method not allowed" });
    return json(ctx, 200, {
      items: [
        { kind: "webhook", status: "buildable", reason: null },
        {
          kind: "teams_webhook",
          status: "degraded",
          reason: "teams_workflows_commercial_and_gcc_only",
        },
        { kind: "email", status: "not_built", reason: "email_transport_not_built" },
      ],
    });
  }
  if (head === "channels" && parts[2] === "test" && parts.length === 3) {
    if (method !== "POST") return json(ctx, 405, { error: "method not allowed" });
    const found = state.channels.find((c) => c.doc["channel_id"] === parts[1]);
    if (found === undefined) return problem(ctx, 404, "not_found", "channel_not_found");
    return json(
      ctx,
      200,
      parts[1] === NOTIFICATION_FLAKY_CHANNEL_ID
        ? { ok: false, status_code: 500, reason_code: "http_500" }
        : { ok: true, status_code: 200, reason_code: null },
    );
  }
  if (head === "channels") {
    return crud(
      ctx,
      {
        items: state.channels,
        idField: "channel_id",
        prefix: "channel",
        view: channelView,
        set: (next) => {
          state.channels = next;
        },
        refuse: channelRefusal,
      },
      parts.slice(1),
    );
  }
  if (head === "subscriptions") {
    return crud(
      ctx,
      {
        items: state.subs,
        idField: "subscription_id",
        prefix: "subscription",
        view: subscriptionView,
        set: (next) => {
          state.subs = next;
        },
        refuse: subscriptionRefusal,
      },
      parts.slice(1),
    );
  }
  if (head === "deliveries" && parts.length === 1) {
    if (method !== "GET") return json(ctx, 405, { error: "method not allowed" });
    const status = ctx.url.searchParams.get("status");
    const channelId = ctx.url.searchParams.get("channel_id");
    const limit = Number(ctx.url.searchParams.get("limit") ?? "100");
    const items = state.deliveries
      .filter((d) => status === null || status === "" || d["status"] === status)
      .filter((d) => channelId === null || channelId === "" || d["channel_id"] === channelId)
      .slice(0, Number.isFinite(limit) && limit > 0 ? limit : 100);
    return json(ctx, 200, { items });
  }
  return problem(ctx, 404, "not_found", "unknown_route");
}

export const handle: FeatureMockHandler = (ctx) => {
  // The registry test passes an empty context; a handler must pass on anything it cannot read.
  const url = (ctx as { url?: URL }).url;
  if (url === undefined) return false;
  const path = url.pathname;
  if (path !== NOTIFICATIONS_API && !path.startsWith(`${NOTIFICATIONS_API}/`)) return false;
  if (!ctx.authorized) {
    json(ctx, 401, { error: "missing or unrecognised token" });
    return true;
  }
  if (ctx.role !== "admin") {
    problem(ctx, 403, "forbidden", "customer_scope_required");
    return true;
  }
  void route(ctx, path.slice(NOTIFICATIONS_API.length));
  return true;
};
