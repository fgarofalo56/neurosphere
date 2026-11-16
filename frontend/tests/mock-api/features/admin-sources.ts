import type { FeatureMockContext, FeatureMockHandler } from "./context.ts";

/**
 * PRP-57 admin console part 2 mock: producers (PRP-41), connector configurations (PRP-42), price
 * sheets, budgets and the review policy (PRP-44), stored feature settings by key (PRP-45) and
 * catalog import. Shapes follow services/api/openapi.json. Every id and value is SYNTHETIC.
 *
 * Persona gate (a stand-in for the API's permission checks): every route needs `admin`; any other
 * persona gets the 403 path. The one-time producer secret appears in exactly two response bodies:
 * producer create and producer rotate. State is module-level; a spec that changes it calls
 * `resetAdminSources()`. `GET /settings` (the list) belongs to admin-core; this module answers only
 * `/settings/{key}` so the two never clash.
 */

const SOURCES = "/api/v1/admin/sources";
const PLATFORM = "/api/v1/admin/platform";
const SETTINGS = "/api/v1/admin/system/settings/";
const IMPORT = "/api/v1/catalog/import";

export const SOURCES_PRODUCER_ID = "ingest-app-a";
/** Every write for this producer answers 409 stale_version. */
export const SOURCES_PRODUCER_STALE = "ingest-stale";
export const SOURCES_CONNECTOR_ID = "gw-poll-main";
export const SOURCES_CONNECTOR_STALE = "gw-poll-stale";
export const SOURCES_DOMAIN = "commercial:e2e:sandbox:domain:finance";
/** A synthetic value that looks like a generated secret; it must reach the DOM once only. */
export const SOURCES_SECRET = "SYNTHETICsecretValueForTestsOnly0123456789abcdefghij";
export const SOURCES_NEXT_SECRET = "SYNTHETICrotatedSecretForTestsOnly0123456789abcdefgh";
export const SOURCES_BUDGET_ID = "finance-monthly";
export const SOURCES_BUDGET_STALE = "finance-stale";
export const SOURCES_PRICE_SHEET_NEWEST = "azure-2026-11";
export const SOURCES_SETTING_KEYS = [
  "copilot",
  "judge",
  "search",
  "scan",
  "mcp_server",
  "write_targets",
] as const;
/** A copilot endpoint containing this text answers 422 with the validator text. */
export const SOURCES_BAD_ENDPOINT = "https://wrong-cloud.invalid";
export const SOURCES_CROSS_CLOUD_TEXT = "endpoint belongs to another cloud";

interface Producer {
  producer_id: string;
  customer_id: string;
  cloud: string;
  sources: { source_id: string; observation_kind: string }[];
  status: "active" | "disabled";
  rotated_at: string | null;
  version: number;
  updated_at: string;
}
interface Connector {
  connector_id: string;
  connector_kind: string;
  domain_ids: string[];
  settings: Record<string, unknown>;
  credential: Record<string, unknown> | null;
  enabled: boolean;
  status: string;
  version: number;
  updated_at: string;
  updated_by: string;
  warnings?: string[];
}
interface Budget {
  budget_id: string;
  domain_id: string;
  period: string;
  amount: string;
  currency: string;
  thresholds_percent: number[];
  tags_filter: null;
  status: string;
  version: number;
  updated_at: string;
  updated_by: string;
}
interface PriceSheet {
  snapshot_id: string;
  source: string;
  source_url: string;
  retrieval_date: string;
  effective_date: string;
  currency: string;
  clouds: string[];
  synthetic: boolean;
  content_hash: string;
  row_count: number;
  notes: string;
}
interface Setting {
  key: string;
  version: number;
  body: Record<string, unknown> | null;
}

const STAMP = "2026-11-10T09:00:00Z";
const PERM = "action.approve";

function policy(sla: number): Record<string, unknown> {
  return {
    self_approval_forbidden: true,
    approver_permission: PERM,
    assignment_timeout_seconds: 3600,
    sla_seconds: sla,
    escalation_step_seconds: 7200,
    max_escalations: 2,
    expiry_seconds: 259_200,
  };
}

function initialPolicy(): Record<string, unknown> {
  return {
    schema_version: "1.0.0",
    policy_version: "policy-1",
    kind_defaults: [
      { review_kind: "maker_checker", policy: policy(14_400) },
      { review_kind: "relationship", policy: policy(86_400) },
    ],
    action_overrides: [
      { review_kind: "maker_checker", action_kind: "model_swap", policy: policy(5415) },
    ],
  };
}

function initialProducers(): Producer[] {
  const base = { customer_id: "e2e", cloud: "commercial", version: 1, updated_at: STAMP };
  return [
    {
      ...base,
      producer_id: SOURCES_PRODUCER_ID,
      sources: [{ source_id: "apim-main", observation_kind: "gateway" }],
      status: "active",
      rotated_at: "2026-11-01T08:00:00Z",
    },
    {
      ...base,
      producer_id: SOURCES_PRODUCER_STALE,
      sources: [{ source_id: "app-stale", observation_kind: "application" }],
      status: "active",
      rotated_at: null,
    },
  ];
}

function initialConnectors(): Connector[] {
  const base = {
    domain_ids: [SOURCES_DOMAIN],
    credential: {
      kind: "key_vault_secret",
      secret_uri: "https://kv-e2e.vault.azure.net/secrets/gw-poll",
      managed_identity_client_id: null,
    },
    enabled: true,
    status: "active",
    version: 1,
    updated_at: STAMP,
    updated_by: "psn-mock-admin",
  };
  return [
    {
      ...base,
      connector_id: SOURCES_CONNECTOR_ID,
      connector_kind: "gateway_poll",
      settings: { poll_interval_seconds: 300 },
    },
    {
      ...base,
      connector_id: SOURCES_CONNECTOR_STALE,
      connector_kind: "billing_export",
      settings: { container: "exports" },
    },
  ];
}

function initialBudgets(): Budget[] {
  const base = {
    domain_id: SOURCES_DOMAIN,
    period: "monthly",
    currency: "USD",
    thresholds_percent: [50, 80, 100],
    tags_filter: null,
    status: "active",
    version: 1,
    updated_at: STAMP,
    updated_by: "psn-mock-admin",
  };
  return [
    { ...base, budget_id: SOURCES_BUDGET_ID, amount: "1500.10" },
    { ...base, budget_id: SOURCES_BUDGET_STALE, amount: "0.1" },
  ];
}

function initialSheets(): PriceSheet[] {
  const base = {
    source: "provider_price_sheet",
    source_url: "https://prices.example.invalid/sheet",
    currency: "USD",
    clouds: ["commercial"],
    synthetic: true,
    notes: "synthetic",
  };
  return [
    {
      ...base,
      snapshot_id: "azure-2026-10",
      retrieval_date: "2026-10-02",
      effective_date: "2026-10-01",
      content_hash: "sha256:1111",
      row_count: 120,
    },
    {
      ...base,
      snapshot_id: SOURCES_PRICE_SHEET_NEWEST,
      retrieval_date: "2026-11-02",
      effective_date: "2026-11-01",
      content_hash: "sha256:2222",
      row_count: 125,
    },
  ];
}

function initialSettings(): Setting[] {
  const cred = {
    kind: "managed_identity",
    managed_identity_client_id: "11111111-1111-4111-8111-111111111111",
  };
  return [
    {
      key: "copilot",
      version: 3,
      body: {
        schema_version: "1.0.0",
        setting_key: "copilot",
        enabled: true,
        copilot: {
          endpoint: "https://oai-e2e.openai.azure.com",
          deployment: "gpt-e2e",
          api_version: "2025-01-01-preview",
          resource_id: null,
          credential: cred,
        },
      },
    },
    { key: "judge", version: 0, body: null },
    { key: "search", version: 0, body: null },
    { key: "scan", version: 0, body: null },
    { key: "mcp_server", version: 0, body: null },
    {
      key: "write_targets",
      version: 1,
      body: {
        schema_version: "1.0.0",
        setting_key: "write_target",
        enabled: false,
        write_target: { target_kind: "apim", credential: cred },
      },
    },
  ];
}

let producers = initialProducers();
let connectors = initialConnectors();
let budgets = initialBudgets();
let sheets = initialSheets();
let settings = initialSettings();
let reviewPolicy = initialPolicy();
let reviewVersion = 1;

export function resetAdminSources(): void {
  producers = initialProducers();
  connectors = initialConnectors();
  budgets = initialBudgets();
  sheets = initialSheets();
  settings = initialSettings();
  reviewPolicy = initialPolicy();
  reviewVersion = 1;
}

function json(
  ctx: FeatureMockContext,
  status: number,
  body: unknown,
  extra: Record<string, string> = {},
  type = "application/json",
): void {
  ctx.res.writeHead(status, { "content-type": type, ...ctx.cors, ...extra });
  ctx.res.end(typeof body === "string" ? body : JSON.stringify(body));
}

function problem(ctx: FeatureMockContext, status: number, code: string, detail: string): void {
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
      reason: detail,
      retryable: false,
      correlation_id: ctx.correlationId,
    },
    {},
    "application/problem+json",
  );
}

async function readJson(ctx: FeatureMockContext): Promise<Record<string, unknown>> {
  try {
    const parsed: unknown = JSON.parse(await ctx.readBody());
    return typeof parsed === "object" && parsed !== null ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

const q = (version: number, prefix: string): string => `"${prefix}-${version}"`;
const stale = (ctx: FeatureMockContext, version: number, prefix: string): boolean => {
  const header = ctx.req.headers["if-match"];
  return header !== undefined && header !== q(version, prefix);
};
const trail = (rest: string): string[] =>
  rest
    .replace(/^\//, "")
    .split("/")
    .filter((p) => p !== "")
    .map(decodeURIComponent);

// ---- producers ------------------------------------------------------------------------------

async function producerRoutes(ctx: FeatureMockContext, rest: string): Promise<void> {
  const method = ctx.req.method ?? "GET";
  const parts = trail(rest);
  if (parts.length === 0) {
    if (method === "GET") return json(ctx, 200, { items: producers, truncated: false });
    if (method !== "POST") return json(ctx, 405, { error: "method not allowed" });
    const body = await readJson(ctx);
    const id = typeof body["producer_id"] === "string" ? body["producer_id"] : "";
    if (!/^[A-Za-z0-9_-]{1,128}$/.test(id)) {
      return problem(ctx, 422, "invalid_schema", "producer_id does not match the allowed pattern");
    }
    if (producers.some((p) => p.producer_id === id)) {
      return problem(ctx, 409, "conflict", "producer_exists");
    }
    const sources = (body["sources"] ?? {}) as Record<string, string>;
    producers = [
      ...producers,
      {
        producer_id: id,
        customer_id: "e2e",
        cloud: String(body["cloud"] ?? "commercial"),
        sources: Object.entries(sources).map(([source_id, observation_kind]) => ({
          source_id,
          observation_kind,
        })),
        status: "active",
        rotated_at: null,
        version: 1,
        updated_at: STAMP,
      },
    ];
    return json(ctx, 201, issued(id, SOURCES_SECRET));
  }
  const producer = producers.find((p) => p.producer_id === parts[0]);
  if (producer === undefined) return problem(ctx, 404, "not_found", "producer_not_found");
  if (parts.length === 1) {
    if (method !== "GET") return json(ctx, 405, { error: "method not allowed" });
    return json(ctx, 200, producer, { etag: q(producer.version, "producer") });
  }
  if (method !== "POST") return json(ctx, 405, { error: "method not allowed" });
  if (producer.producer_id === SOURCES_PRODUCER_STALE || stale(ctx, producer.version, "producer")) {
    return problem(ctx, 409, "stale_version", "etag_mismatch");
  }
  const action = parts[1];
  if (action === "rotate") {
    producer.rotated_at = "2026-11-12T10:00:00Z";
    producer.version += 1;
    return json(ctx, 200, issued(producer.producer_id, SOURCES_NEXT_SECRET));
  }
  if (action === "disable" || action === "enable") {
    producer.status = action === "disable" ? "disabled" : "active";
    producer.version += 1;
    return json(ctx, 200, producer, { etag: q(producer.version, "producer") });
  }
  return problem(ctx, 404, "not_found", "unknown_route");
}

function issued(id: string, secret: string): Record<string, unknown> {
  return {
    schema_version: "1.0.0",
    producer_id: id,
    secret,
    secret_sha256: "a".repeat(64),
    issued_at: "2026-11-12T10:00:00Z",
    shown_once: true,
  };
}

// ---- connectors -----------------------------------------------------------------------------

const VAULT =
  /^https:\/\/[a-z][a-z0-9-]{1,22}[a-z0-9]\.vault\.(azure\.net|usgovcloudapi\.net)\/secrets\/[A-Za-z0-9-]{1,127}(\/[0-9a-f]{32})?$/;

function credentialProblem(body: Record<string, unknown>): string | undefined {
  const cred = body["credential"];
  if (cred === null || cred === undefined) return undefined;
  const c = cred as Record<string, unknown>;
  if (c["kind"] === "key_vault_secret") {
    return typeof c["secret_uri"] === "string" && VAULT.test(c["secret_uri"])
      ? undefined
      : "/body/credential/secret_uri: not a Key Vault secret reference";
  }
  if (c["kind"] === "managed_identity") {
    return typeof c["managed_identity_client_id"] === "string" &&
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
        c["managed_identity_client_id"],
      )
      ? undefined
      : "/body/credential/managed_identity_client_id: not a client id";
  }
  return "/body/credential/kind: unknown kind";
}

async function connectorRoutes(ctx: FeatureMockContext, rest: string): Promise<void> {
  const method = ctx.req.method ?? "GET";
  const parts = trail(rest);
  const fromBody = (body: Record<string, unknown>, version: number): Connector => ({
    connector_id: String(body["connector_id"]),
    connector_kind: String(body["connector_kind"]),
    domain_ids: (body["domain_ids"] ?? []) as string[],
    settings: (body["settings"] ?? {}) as Record<string, unknown>,
    credential: (body["credential"] ?? null) as Record<string, unknown> | null,
    enabled: body["enabled"] === true,
    status: "active",
    version,
    updated_at: STAMP,
    updated_by: "psn-mock-admin",
    ...(body["connector_kind"] === "otel" ? { warnings: ["producer_not_in_store"] } : {}),
  });
  if (parts.length === 0) {
    if (method === "GET") {
      const kind = ctx.url.searchParams.get("connector_kind");
      return json(ctx, 200, {
        items: connectors.filter(
          (c) =>
            c.status !== "retired" && (kind === null || kind === "" || c.connector_kind === kind),
        ),
      });
    }
    if (method !== "POST") return json(ctx, 405, { error: "method not allowed" });
    const body = await readJson(ctx);
    const problemText = credentialProblem(body);
    if (problemText !== undefined) {
      return problem(ctx, 422, "invalid_schema", problemText);
    }
    if (connectors.some((c) => c.connector_id === body["connector_id"])) {
      return problem(ctx, 409, "conflict", "connector_exists");
    }
    const created = fromBody(body, 1);
    connectors = [...connectors, created];
    return json(ctx, 201, created, { etag: q(1, "connector") });
  }
  const connector = connectors.find((c) => c.connector_id === parts[0]);
  if (connector === undefined) return problem(ctx, 404, "not_found", "connector_not_found");
  if (method === "GET" && parts.length === 1) {
    return json(ctx, 200, connector, { etag: q(connector.version, "connector") });
  }
  if (method !== "PUT" && method !== "DELETE" && method !== "POST") {
    return json(ctx, 405, { error: "method not allowed" });
  }
  if (
    connector.connector_id === SOURCES_CONNECTOR_STALE ||
    stale(ctx, connector.version, "connector")
  ) {
    return problem(ctx, 409, "stale_version", "etag_mismatch");
  }
  if (method === "PUT") {
    const body = await readJson(ctx);
    const problemText = credentialProblem(body);
    if (problemText !== undefined) return problem(ctx, 422, "invalid_schema", problemText);
    const next = fromBody(body, connector.version + 1);
    connectors = connectors.map((c) => (c.connector_id === connector.connector_id ? next : c));
    return json(ctx, 200, next, { etag: q(next.version, "connector") });
  }
  if (method === "DELETE") connector.status = "retired";
  else if (parts[1] === "enable" || parts[1] === "disable")
    connector.enabled = parts[1] === "enable";
  else return problem(ctx, 404, "not_found", "unknown_route");
  connector.version += 1;
  return json(ctx, 200, connector, { etag: q(connector.version, "connector") });
}

// ---- platform: price sheets, budgets, review policy -----------------------------------------

const AMOUNT = /^(0|[1-9][0-9]{0,17})(\.[0-9]{1,12})?$/;

const reply = (...args: Parameters<typeof json>): true => {
  json(...args);
  return true;
};
const fail = (...args: Parameters<typeof problem>): true => {
  problem(...args);
  return true;
};

async function platformRoutes(ctx: FeatureMockContext, rest: string): Promise<boolean> {
  const method = ctx.req.method ?? "GET";
  const parts = trail(rest);
  if (parts[0] === "price-sheets" && parts.length === 1) {
    if (method === "GET") return reply(ctx, 200, { items: sheets });
    if (method !== "POST") return reply(ctx, 405, { error: "method not allowed" });
    const body = await readJson(ctx);
    const rows = Array.isArray(body["rows"]) ? (body["rows"] as Record<string, unknown>[]) : [];
    const badIndex = rows.findIndex(
      (r) => typeof r["retail_price"] !== "string" || !AMOUNT.test(r["retail_price"]),
    );
    if (rows.length === 0 || badIndex >= 0) {
      return fail(
        ctx,
        422,
        "invalid_schema",
        `/body/rows/${Math.max(badIndex, 0)}/retail_price: not a decimal amount`,
      );
    }
    const id = String(body["snapshot_id"]);
    const existing = sheets.find((s) => s.snapshot_id === id);
    const sheet: PriceSheet = existing ?? {
      snapshot_id: id,
      source: String(body["source"]),
      source_url: String(body["source_url"]),
      retrieval_date: String(body["retrieval_date"]),
      effective_date: String(body["effective_date"]),
      currency: String(body["currency"]),
      clouds: (body["clouds"] ?? []) as string[],
      synthetic: body["synthetic"] === true,
      content_hash: "sha256:3333",
      row_count: rows.length,
      notes: String(body["notes"] ?? ""),
    };
    if (existing === undefined) sheets = [...sheets, sheet];
    return reply(ctx, existing === undefined ? 201 : 200, {
      sheet,
      created: existing === undefined,
      coverage: {
        snapshot_id: id,
        rows: rows.length,
        models_priced: 2,
        models_incomplete: [],
        rows_without_token_meter: 0,
        warnings: [],
      },
    });
  }
  if (parts[0] === "budgets") {
    if (parts.length === 1) {
      if (method === "GET") {
        return reply(ctx, 200, { items: budgets.filter((b) => b.status !== "retired") });
      }
      if (method !== "POST") return reply(ctx, 405, { error: "method not allowed" });
      const body = await readJson(ctx);
      if (typeof body["amount"] !== "string" || !AMOUNT.test(body["amount"])) {
        return fail(ctx, 422, "invalid_schema", "/body/amount: not a decimal amount");
      }
      if (budgets.some((b) => b.budget_id === body["budget_id"])) {
        return fail(ctx, 409, "conflict", "budget_exists");
      }
      const created = budgetFrom(body, 1);
      budgets = [...budgets, created];
      return reply(ctx, 201, created, { etag: q(1, "budget") });
    }
    const budget = budgets.find((b) => b.budget_id === parts[1]);
    if (budget === undefined) return fail(ctx, 404, "not_found", "budget_not_found");
    if (method === "GET") {
      return reply(ctx, 200, budget, { etag: q(budget.version, "budget") });
    }
    if (budget.budget_id === SOURCES_BUDGET_STALE || stale(ctx, budget.version, "budget")) {
      return fail(ctx, 409, "stale_version", "etag_mismatch");
    }
    if (method === "PUT") {
      const body = await readJson(ctx);
      if (typeof body["amount"] !== "string" || !AMOUNT.test(body["amount"])) {
        return fail(ctx, 422, "invalid_schema", "/body/amount: not a decimal amount");
      }
      const next = budgetFrom(body, budget.version + 1);
      budgets = budgets.map((b) => (b.budget_id === budget.budget_id ? next : b));
      return reply(ctx, 200, next, { etag: q(next.version, "budget") });
    }
    if (method === "DELETE") {
      budget.status = "retired";
      budget.version += 1;
      return reply(ctx, 200, budget);
    }
    return reply(ctx, 405, { error: "method not allowed" });
  }
  if (parts[0] === "review-policy" && parts.length === 1) {
    if (method === "GET") {
      return reply(
        ctx,
        200,
        {
          source: "stored",
          version: reviewVersion,
          policy_version: String(reviewPolicy["policy_version"]),
          document: reviewPolicy,
        },
        { etag: q(reviewVersion, "policy") },
      );
    }
    if (method !== "PUT") return reply(ctx, 405, { error: "method not allowed" });
    if (stale(ctx, reviewVersion, "policy")) {
      return fail(ctx, 409, "stale_version", "etag_mismatch");
    }
    const body = await readJson(ctx);
    const all = [
      ...((body["kind_defaults"] ?? []) as { policy: Record<string, number> }[]),
      ...((body["action_overrides"] ?? []) as { policy: Record<string, number> }[]),
    ];
    if (all.some((e) => (e.policy["expiry_seconds"] ?? 0) < (e.policy["sla_seconds"] ?? 0))) {
      return fail(
        ctx,
        422,
        "invalid_schema",
        "expiry_seconds must not be shorter than sla_seconds",
      );
    }
    const before = reviewPolicy;
    reviewPolicy = body;
    reviewVersion += 1;
    return reply(
      ctx,
      200,
      {
        source: "stored",
        version: reviewVersion,
        policy_version: String(body["policy_version"]),
        document: body,
        before,
        changes: [],
      },
      { etag: q(reviewVersion, "policy") },
    );
  }
  return false;
}

function budgetFrom(body: Record<string, unknown>, version: number): Budget {
  return {
    budget_id: String(body["budget_id"]),
    domain_id: String(body["domain_id"]),
    period: String(body["period"]),
    amount: String(body["amount"]),
    currency: String(body["currency"]),
    thresholds_percent: (body["thresholds_percent"] ?? []) as number[],
    tags_filter: null,
    status: "active",
    version,
    updated_at: STAMP,
    updated_by: "psn-mock-admin",
  };
}

// ---- settings by key --------------------------------------------------------------------------

function settingView(s: Setting): Record<string, unknown> {
  const stored = s.body !== null;
  return {
    key: s.key,
    source: stored ? "stored" : "default",
    stored_revision: stored ? s.version : null,
    applied_revision: stored ? s.version - 1 : null,
    restart_required: stored && s.version > 0,
    applied_by_runtime: s.key !== "write_targets",
    etag: stored ? q(s.version, `setting-${s.key}`) : null,
    entries: stored
      ? [
          {
            document_id: `system.${s.key}`,
            version: s.version,
            etag: q(s.version, "doc"),
            value: s.body,
          },
        ]
      : [],
  };
}

function diffOf(
  before: Record<string, unknown> | null,
  after: Record<string, unknown>,
): { pointer: string; before: unknown; after: unknown }[] {
  const out: { pointer: string; before: unknown; after: unknown }[] = [];
  const walk = (b: unknown, a: unknown, pointer: string): void => {
    if (a !== null && typeof a === "object" && !Array.isArray(a)) {
      const bo = (b !== null && typeof b === "object" ? b : {}) as Record<string, unknown>;
      for (const [k, v] of Object.entries(a as Record<string, unknown>))
        walk(bo[k], v, `${pointer}/${k}`);
      return;
    }
    if (JSON.stringify(b) !== JSON.stringify(a)) out.push({ pointer, before: b, after: a });
  };
  walk(before, after, "");
  return out;
}

async function settingRoutes(ctx: FeatureMockContext, key: string): Promise<void> {
  const method = ctx.req.method ?? "GET";
  const setting = settings.find((s) => s.key === key);
  if (setting === undefined) return problem(ctx, 404, "not_found", "unknown_setting_key");
  if (method === "GET") {
    const view = settingView(setting);
    return json(ctx, 200, view, view["etag"] === null ? {} : { etag: String(view["etag"]) });
  }
  if (method !== "PUT") return json(ctx, 405, { error: "method not allowed" });
  const header = ctx.req.headers["if-match"];
  if (setting.body !== null && header !== q(setting.version, `setting-${key}`)) {
    return problem(ctx, 409, "stale_version", "etag_mismatch");
  }
  const body = await readJson(ctx);
  const member = (body[key] ?? {}) as Record<string, unknown>;
  if (
    typeof member["endpoint"] === "string" &&
    member["endpoint"].startsWith(SOURCES_BAD_ENDPOINT)
  ) {
    return problem(
      ctx,
      422,
      "invalid_schema",
      `/body/${key}/endpoint: ${SOURCES_CROSS_CLOUD_TEXT}`,
    );
  }
  const diff = diffOf(setting.body, body);
  setting.body = body;
  setting.version += 1;
  return json(
    ctx,
    200,
    {
      key,
      document_id: `system.${key}`,
      version: setting.version,
      etag: q(setting.version, `setting-${key}`),
      stored_revision: setting.version,
      applied_revision: setting.version - 1,
      restart_required: true,
      diff,
    },
    { etag: q(setting.version, `setting-${key}`) },
  );
}

// ---- catalog import -------------------------------------------------------------------------

async function importRoute(ctx: FeatureMockContext): Promise<void> {
  if ((ctx.req.method ?? "GET") !== "POST") return json(ctx, 405, { error: "method not allowed" });
  const body = await readJson(ctx);
  const items = Array.isArray(body["items"]) ? (body["items"] as Record<string, unknown>[]) : [];
  if (items.length === 0 || items.length > 100) {
    return problem(ctx, 422, "invalid_schema", "/body/items: between 1 and 100 items");
  }
  const dryRun = body["dry_run"] === true;
  const rejected = items.some((i) => i["reject"] === true || typeof i["id"] !== "string");
  const results = items.map((item, index) => {
    const id = typeof item["id"] === "string" ? item["id"] : null;
    if (id === null || item["reject"] === true) {
      return { index, id, status: "rejected", code: id === null ? "missing_id" : "invalid_schema" };
    }
    if (dryRun) return { index, id, status: "valid", code: null };
    return { index, id, status: rejected ? "skipped" : "created", code: null };
  });
  return json(ctx, 200, { committed: !dryRun && !rejected, dry_run: dryRun, items: results });
}

export const handle: FeatureMockHandler = (ctx) => {
  // The registry test passes an empty context; a handler must pass on anything it cannot read.
  const url = (ctx as { url?: URL }).url;
  if (url === undefined) return false;
  const path = url.pathname;
  const sources = path === `${SOURCES}/producers` || path.startsWith(`${SOURCES}/producers/`);
  const conns = path === `${SOURCES}/connectors` || path.startsWith(`${SOURCES}/connectors/`);
  const platform = ["/price-sheets", "/budgets", "/review-policy"].some(
    (s) => path === `${PLATFORM}${s}` || path.startsWith(`${PLATFORM}${s}/`),
  );
  const setting = path.startsWith(SETTINGS);
  const imp = path === IMPORT;
  if (!sources && !conns && !platform && !setting && !imp) return false;
  if (!ctx.authorized) {
    json(ctx, 401, { error: "missing or unrecognised token" });
    return true;
  }
  if (ctx.role !== "admin") {
    problem(ctx, 403, "forbidden", "permission_missing");
    return true;
  }
  if (sources) void producerRoutes(ctx, path.slice(`${SOURCES}/producers`.length));
  else if (conns) void connectorRoutes(ctx, path.slice(`${SOURCES}/connectors`.length));
  else if (platform) {
    void platformRoutes(ctx, path.slice(PLATFORM.length)).then((handled) => {
      if (!handled) problem(ctx, 404, "not_found", "unknown_route");
    });
  } else if (setting) void settingRoutes(ctx, decodeURIComponent(path.slice(SETTINGS.length)));
  else void importRoute(ctx);
  return true;
};
