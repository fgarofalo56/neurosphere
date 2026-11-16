import type { FeatureMockContext, FeatureMockHandler } from "./context.ts";

/**
 * PRP-53 admin console mock: identity (PRP-39), domain registry (PRP-44), system status
 * (PRP-45) and audit search/export (PRP-40) routes. Shapes follow services/api/openapi.json.
 * Every id, pseudonym and hash is SYNTHETIC. Persona gate (a stand-in for the API's permission
 * checks): identity, platform and system need `admin`; audit search needs `admin` or `auditor`;
 * export needs `admin` (a stand-in for `audit.export`, so an auditor sees the 403 path). State is
 * module-level; a spec that changes it calls `resetAdminCore()`.
 */

const IDENTITY = "/api/v1/admin/identity/principals";
const PLATFORM_DOMAINS = "/api/v1/admin/platform/domains";
const SYSTEM = "/api/v1/admin/system";
const AUDIT = "/api/v1/audit";

const HEX = "0123456789abcdef";
function principalId(seed: number): string {
  let out = "";
  for (let i = 0; i < 64; i += 1) out += HEX[(seed * 11 + i * 7 + (i >> 1)) % 16];
  return `commercial:e2e:entra:person:p-${out}`;
}

export const ADMIN_PRINCIPAL_ID = principalId(1);
export const ADMIN_PRINCIPAL_REVOKED = principalId(2);
/** Every write for this principal answers 409 stale_version. */
export const ADMIN_PRINCIPAL_STALE = principalId(3);
/** Reading this principal answers 403. */
export const ADMIN_PRINCIPAL_FORBIDDEN = principalId(4);

export const ADMIN_DOMAIN_FINANCE = "commercial:e2e:catalog:domain:finance";
export const ADMIN_DOMAIN_PEOPLE = "commercial:e2e:catalog:domain:people";
export const ADMIN_DOMAIN_ARCHIVE = "commercial:e2e:catalog:domain:archive";
export const ADMIN_DOMAIN_CONTROL = "commercial:e2e:catalog:domain:control";
/** Creating this domain answers 422 with the reserved-name text. */
export const ADMIN_DOMAIN_RESERVED = "commercial:e2e:catalog:domain:identity-admin";
export const ADMIN_RESERVED_TEXT =
  "domain name identity-admin is reserved for a customer-level audit chain";
/** Retiring this domain answers 409 stale_version. */
export const ADMIN_DOMAIN_STALE = ADMIN_DOMAIN_PEOPLE;

/** Audit rows: more than one page at the page size the UI asks for (25). */
export const ADMIN_AUDIT_COUNT = 31;
export const ADMIN_AUDIT_DENIED_COUNT = 10;
export const ADMIN_SETTING_KEYS = [
  "copilot",
  "judge",
  "search",
  "scan",
  "mcp_server",
  "write_targets",
] as const;
/** Host-like and secret-like values the system routes may carry; the page must never show them. */
export const ADMIN_SECRET_PROBE = "https://probe-secret-host.invalid/key=s3cr3t-value";

interface Assignment {
  assignment_id: string;
  role: string;
  domain_ids: string[];
  expires_at: string | null;
  reason: string | null;
}
interface Grant {
  grant_id: string;
  resource_id: string;
  permissions: string[];
  expires_at: string;
  reason: string;
}
interface Revocation {
  revoked: boolean;
  mode: string | null;
  revoked_at: string | null;
  reason: string | null;
  revoked_by: string | null;
}
interface PrincipalState {
  id: string;
  version: number;
  memberships: string[];
  assignments: Assignment[];
  grants: Grant[];
  revocation: Revocation;
}
interface DomainState {
  domain_id: string;
  display_name: string;
  classification: string;
  residency_region: string;
  status: string;
  is_control_domain: boolean;
  version: number;
}

const NOT_REVOKED: Revocation = {
  revoked: false,
  mode: null,
  revoked_at: null,
  reason: null,
  revoked_by: null,
};

function initialPrincipals(): PrincipalState[] {
  return [
    {
      id: ADMIN_PRINCIPAL_ID,
      version: 1,
      memberships: [ADMIN_DOMAIN_FINANCE],
      assignments: [
        {
          assignment_id: "role-analyst-seed",
          role: "analyst",
          domain_ids: [ADMIN_DOMAIN_FINANCE],
          expires_at: "2099-01-01T00:00:00Z",
          reason: "onboarding",
        },
        {
          assignment_id: "role-viewer-expired",
          role: "viewer",
          domain_ids: [ADMIN_DOMAIN_FINANCE],
          expires_at: "2020-01-01T00:00:00Z",
          reason: "trial",
        },
      ],
      grants: [
        {
          grant_id: "grant-seed",
          resource_id: "commercial:e2e:catalog:report:quarterly",
          permissions: ["read"],
          expires_at: "2099-01-01T00:00:00Z",
          reason: "audit_support",
        },
      ],
      revocation: { ...NOT_REVOKED },
    },
    {
      id: ADMIN_PRINCIPAL_REVOKED,
      version: 1,
      memberships: [ADMIN_DOMAIN_PEOPLE],
      assignments: [],
      grants: [],
      revocation: {
        revoked: true,
        mode: "until_lifted",
        revoked_at: "2026-10-01T09:00:00Z",
        reason: "offboarding",
        revoked_by: principalId(1),
      },
    },
    {
      id: ADMIN_PRINCIPAL_STALE,
      version: 1,
      memberships: [],
      assignments: [],
      grants: [],
      revocation: { ...NOT_REVOKED },
    },
    {
      id: ADMIN_PRINCIPAL_FORBIDDEN,
      version: 1,
      memberships: [],
      assignments: [],
      grants: [],
      revocation: { ...NOT_REVOKED },
    },
  ];
}

function initialDomains(): DomainState[] {
  const base = { classification: "internal", residency_region: "eastus", version: 1 };
  return [
    {
      ...base,
      domain_id: ADMIN_DOMAIN_FINANCE,
      display_name: "Finance",
      status: "active",
      is_control_domain: false,
    },
    {
      ...base,
      domain_id: ADMIN_DOMAIN_PEOPLE,
      display_name: "People",
      status: "active",
      is_control_domain: false,
    },
    {
      ...base,
      domain_id: ADMIN_DOMAIN_ARCHIVE,
      display_name: "Archive",
      status: "retired",
      is_control_domain: false,
    },
    {
      ...base,
      classification: "restricted",
      domain_id: ADMIN_DOMAIN_CONTROL,
      display_name: "Control",
      status: "active",
      is_control_domain: true,
    },
  ];
}

let principals = initialPrincipals();
let domains = initialDomains();

export function resetAdminCore(): void {
  principals = initialPrincipals();
  domains = initialDomains();
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

function etagOf(p: PrincipalState): string {
  return `"principal-${p.version}"`;
}

function summary(p: PrincipalState): Record<string, unknown> {
  return {
    schema_version: "1.0.0",
    principal: { principal_id: p.id, principal_kind: "user" },
    customer_id: "e2e",
    cloud: "commercial",
    policy_version: `pv-${p.version}`,
    memberships: p.memberships,
    assignments: p.assignments,
    grants: p.grants,
    revocation: revocationView(p),
    generated_at: "2026-11-01T12:00:00Z",
  };
}

function revocationView(p: PrincipalState): Record<string, unknown> {
  return {
    schema_version: "1.0.0",
    principal_id: p.id,
    ...p.revocation,
    propagation_bound_seconds: 30,
  };
}

const REASON = /^[a-z][a-z0-9_]{0,63}$/;

function reasonOf(value: unknown): string | undefined {
  return typeof value === "string" && REASON.test(value) ? value : undefined;
}

async function identity(ctx: FeatureMockContext, rest: string): Promise<void> {
  const method = ctx.req.method ?? "GET";
  if (rest === "" || rest === "/") {
    if (method !== "GET") return json(ctx, 405, { error: "method not allowed" });
    const limit = Math.min(Number(ctx.url.searchParams.get("limit") ?? 25), 100);
    const cursor = ctx.url.searchParams.get("cursor");
    const start = cursor === null ? 0 : principals.findIndex((p) => p.id === cursor) + 1;
    const slice = principals.slice(start, start + limit);
    const last = slice[slice.length - 1];
    const more = start + limit < principals.length;
    return json(ctx, 200, {
      items: slice.map(summary),
      next_cursor: more && last !== undefined ? last.id : null,
      truncated: false,
    });
  }
  const parts = rest.replace(/^\//, "").split("/").map(decodeURIComponent);
  const id = parts[0] ?? "";
  const principal = principals.find((p) => p.id === id);
  if (principal === undefined) return problem(ctx, 404, "not_found", "principal_not_found");
  if (id === ADMIN_PRINCIPAL_FORBIDDEN)
    return problem(ctx, 403, "forbidden", "target_out_of_scope");
  const kind = parts[1];
  const itemId = parts[2] ?? "";
  if (parts.length === 1) {
    if (method !== "GET") return json(ctx, 405, { error: "method not allowed" });
    return json(ctx, 200, summary(principal), { etag: etagOf(principal) });
  }
  if (kind === "revocation") return revocation(ctx, principal, method);
  // From here on: a write to an existing principal document.
  if (method !== "PUT" && method !== "DELETE")
    return json(ctx, 405, { error: "method not allowed" });
  const ifMatch = ctx.req.headers["if-match"];
  if (
    principal.id === ADMIN_PRINCIPAL_STALE ||
    (ifMatch !== undefined && ifMatch !== etagOf(principal))
  ) {
    return problem(ctx, 409, "stale_version", "etag_mismatch");
  }
  const body = method === "PUT" ? await readJson(ctx) : {};
  const reason = reasonOf(method === "PUT" ? body["reason"] : ctx.url.searchParams.get("reason"));
  if (reason === undefined)
    return problem(ctx, 422, "invalid_schema", "reason must be a reason code");
  const expiresAt = typeof body["expires_at"] === "string" ? body["expires_at"] : null;
  if (expiresAt !== null && Date.parse(expiresAt) <= Date.now()) {
    return problem(ctx, 422, "invalid_schema", "expires_at must be in the future");
  }
  if (kind === "role-assignments") {
    if (method === "DELETE") {
      principal.assignments = principal.assignments.filter((a) => a.assignment_id !== itemId);
    } else {
      principal.assignments = [
        ...principal.assignments.filter((a) => a.assignment_id !== itemId),
        {
          assignment_id: itemId,
          role: String(body["role"] ?? "viewer"),
          domain_ids: Array.isArray(body["domain_ids"]) ? (body["domain_ids"] as string[]) : [],
          expires_at: expiresAt,
          reason,
        },
      ];
    }
  } else if (kind === "domain-memberships") {
    principal.memberships =
      method === "DELETE"
        ? principal.memberships.filter((d) => d !== itemId)
        : [...new Set([...principal.memberships, itemId])];
  } else if (kind === "grants") {
    if (method === "DELETE") {
      principal.grants = principal.grants.filter((g) => g.grant_id !== itemId);
    } else {
      principal.grants = [
        ...principal.grants.filter((g) => g.grant_id !== itemId),
        {
          grant_id: itemId,
          resource_id: String(body["resource_id"] ?? ""),
          permissions: Array.isArray(body["permissions"]) ? (body["permissions"] as string[]) : [],
          expires_at: expiresAt ?? "",
          reason,
        },
      ];
    }
  } else {
    return problem(ctx, 404, "not_found", "unknown_route");
  }
  principal.version += 1;
  return json(ctx, 200, summary(principal), { etag: etagOf(principal) });
}

async function revocation(
  ctx: FeatureMockContext,
  principal: PrincipalState,
  method: string,
): Promise<void> {
  if (method === "GET") return json(ctx, 200, revocationView(principal));
  if (method === "POST") {
    const body = await readJson(ctx);
    const reason = reasonOf(body["reason"]);
    const mode = body["mode"];
    if (reason === undefined || (mode !== "issued_before" && mode !== "until_lifted")) {
      return problem(ctx, 422, "invalid_schema", "mode and a reason code are required");
    }
    principal.revocation = {
      revoked: true,
      mode,
      revoked_at: "2026-11-02T08:00:00Z",
      reason,
      revoked_by: principalId(1),
    };
    return json(ctx, 200, revocationView(principal));
  }
  if (method === "DELETE") {
    if (reasonOf(ctx.url.searchParams.get("reason")) === undefined) {
      return problem(ctx, 422, "invalid_schema", "reason must be a reason code");
    }
    principal.revocation = { ...NOT_REVOKED };
    return json(ctx, 200, revocationView(principal));
  }
  return json(ctx, 405, { error: "method not allowed" });
}

function domainView(d: DomainState): Record<string, unknown> {
  return {
    ...d,
    control_registered: d.is_control_domain,
    updated_at: "2026-11-01T12:00:00Z",
    updated_by: principalId(1),
  };
}

async function platformDomains(ctx: FeatureMockContext, rest: string): Promise<void> {
  const method = ctx.req.method ?? "GET";
  if (rest === "") {
    if (method === "GET") {
      const includeRetired = ctx.url.searchParams.get("include_retired") === "true";
      return json(ctx, 200, {
        items: domains.filter((d) => includeRetired || d.status === "active").map(domainView),
      });
    }
    if (method === "POST") {
      const body = await readJson(ctx);
      const domainId = String(body["domain_id"] ?? "");
      if (domainId === ADMIN_DOMAIN_RESERVED)
        return problem(ctx, 422, "invalid_schema", ADMIN_RESERVED_TEXT);
      if (domains.some((d) => d.domain_id === domainId)) {
        return problem(ctx, 409, "stale_version", "domain_exists");
      }
      const created: DomainState = {
        domain_id: domainId,
        display_name: String(body["display_name"] ?? ""),
        classification: String(body["classification"] ?? "unknown"),
        residency_region: String(body["residency_region"] ?? ""),
        status: "active",
        is_control_domain: body["is_control_domain"] === true,
        version: 1,
      };
      domains = [...domains, created];
      return json(ctx, 201, domainView(created), { etag: `"domain-1"` });
    }
    return json(ctx, 405, { error: "method not allowed" });
  }
  const single = /^\/([^/]+)$/.exec(rest);
  if (single !== null && method === "GET") {
    const found = domains.find((d) => d.domain_id === decodeURIComponent(single[1] ?? ""));
    if (found === undefined) return problem(ctx, 404, "not_found", "domain_not_found");
    return json(ctx, 200, domainView(found), { etag: `"domain-${found.version}"` });
  }
  const match = /^\/([^/]+)\/retire$/.exec(rest);
  if (match === null || method !== "POST") return problem(ctx, 404, "not_found", "unknown_route");
  const domain = domains.find((d) => d.domain_id === decodeURIComponent(match[1] ?? ""));
  if (domain === undefined) return problem(ctx, 404, "not_found", "domain_not_found");
  if (domain.domain_id === ADMIN_DOMAIN_STALE)
    return problem(ctx, 409, "stale_version", "etag_mismatch");
  if (domain.is_control_domain)
    return problem(ctx, 422, "invalid_schema", "the control domain cannot be retired");
  domain.status = "retired";
  domain.version += 1;
  return json(ctx, 200, domainView(domain), { etag: `"domain-${domain.version}"` });
}

function system(ctx: FeatureMockContext, rest: string): void {
  if (ctx.req.method !== "GET") return json(ctx, 405, { error: "method not allowed" });
  const stored = { status: "loaded", reason: null, invalid_keys: [] };
  if (rest === "/status") {
    return json(ctx, 200, {
      ready: false,
      components: [
        {
          name: "authz",
          state: "ok",
          required: true,
          reason: null,
          blocks_readiness: false,
          step: false,
        },
        {
          name: "ingest",
          state: "failed",
          required: true,
          reason: "ingest_producers_unconfigured",
          blocks_readiness: true,
          step: false,
        },
        {
          name: "copilot",
          state: "disabled",
          required: false,
          reason: "component_disabled",
          blocks_readiness: false,
          step: false,
        },
        {
          name: "scan",
          state: "not_built",
          required: false,
          reason: "not_built",
          blocks_readiness: false,
          step: false,
        },
      ],
      probes: { cosmos: "ok" },
      stored_settings: stored,
    });
  }
  if (rest === "/checklist") {
    const item = (
      id: string,
      component: string,
      status: string,
      reason: string | null,
      required: boolean,
    ) => ({
      schema_version: "1.0.0",
      item_id: id,
      component,
      status,
      reason,
      doc_path: `docs/runbooks/system-settings.md#${id.replaceAll(".", "-")}`,
      required,
    });
    return json(ctx, 200, {
      items: [
        item("stored_settings.store", "admin_config", "complete", null, true),
        item("ingest.producers", "ingest", "missing", "ingest_producers_unconfigured", true),
        item(
          "write_targets.registered",
          "write_targets",
          "error",
          "write_targets_stored_not_registered",
          true,
        ),
        item("optional.copilot", "copilot", "disabled", "component_disabled", false),
        item("auth.customer_binding", "authz", "not_applicable", "local_default_customer", true),
      ],
    });
  }
  if (rest === "/settings") {
    return json(ctx, 200, {
      items: ADMIN_SETTING_KEYS.map((key, i) => ({
        key,
        source: i === 0 ? "stored" : i === 1 ? "env" : "default",
        stored_revision: i === 0 ? 3 : null,
        applied_revision: i === 0 ? 2 : null,
        restart_required: i === 0,
        applied_by_runtime: i !== 5,
        etag: null,
        // A value, host and secret the page must never render.
        entries: [
          { document_id: key, version: 1, etag: "e", value: { endpoint: ADMIN_SECRET_PROBE } },
        ],
      })),
      stored_settings: stored,
    });
  }
  return problem(ctx, 404, "not_found", "unknown_route");
}

const KINDS = ["before", "after", "denied"] as const;

function auditRow(i: number): Record<string, unknown> {
  // The first ADMIN_AUDIT_DENIED_COUNT rows are the denied ones, so the denials tab has content.
  const kind = i < ADMIN_AUDIT_DENIED_COUNT ? "denied" : (KINDS[i % 2] ?? "after");
  const domain = i % 2 === 0 ? ADMIN_DOMAIN_FINANCE : ADMIN_DOMAIN_PEOPLE;
  const minute = String(i % 60).padStart(2, "0");
  const hash = (n: number): string => `sha256:${String(n).padStart(2, "0").repeat(32)}`;
  return {
    domain_id: domain,
    record: {
      schema_version: "1.0.0",
      audit_id: `00000000-0000-4000-8000-${(i + 1).toString(16).padStart(12, "0")}`,
      chain_id: `e2e.${domain.split(":").pop() ?? "x"}`,
      sequence: i,
      previous_hash: i === 0 ? null : hash(i - 1),
      record_hash: hash(i),
      kind,
      recorded_at: `2026-10-20T10:${minute}:00.000000Z`,
      actor: {
        principal_pseudonym: `psn-mock-actor-${i % 4}`,
        principal_kind: "user",
        on_behalf_of: null,
      },
      scope_hash: hash(90),
      correlation_id: `corr-admin-${i}`,
      operation:
        kind === "denied" ? "graph.query" : i % 3 === 0 ? "policy.role_assign" : "action.execute",
      channel: "rest",
      intent_id: null,
      subject: null,
      outcome: kind === "after" ? { result: "succeeded", verified: true, detail: null } : null,
      denial: kind === "denied" ? { code: "forbidden", reason: "domain_out_of_scope" } : null,
    },
  };
}

type Row = ReturnType<typeof auditRow>;
function allRows(): Row[] {
  return Array.from({ length: ADMIN_AUDIT_COUNT }, (_, i) => auditRow(i));
}

function filterRows(ctx: FeatureMockContext, rows: Row[]): Row[] {
  const q = ctx.url.searchParams;
  return rows.filter((row) => {
    const rec = row["record"] as Record<string, unknown> & {
      actor: { principal_pseudonym: string };
      outcome: { result: string } | null;
    };
    const eq = (name: string, actual: unknown): boolean => {
      const want = q.get(name);
      return want === null || want === "" || want === actual;
    };
    return (
      eq("domain", row["domain_id"]) &&
      eq("operation", rec["operation"]) &&
      eq("kind", rec["kind"]) &&
      eq("outcome", rec.outcome?.result) &&
      eq("actor", rec.actor.principal_pseudonym) &&
      eq("correlation_id", rec["correlation_id"])
    );
  });
}

/** `since` and `until` are required and capped at 31 days, like the API. */
function rangeError(ctx: FeatureMockContext): string | undefined {
  const since = Date.parse(ctx.url.searchParams.get("since") ?? "");
  const until = Date.parse(ctx.url.searchParams.get("until") ?? "");
  if (Number.isNaN(since) || Number.isNaN(until)) return "since and until are required";
  if (until <= since) return "until must be after since";
  if (until - since > 31 * 86_400_000) return "the time range is capped at 31 days";
  return undefined;
}

function csvOf(rows: Row[]): string {
  const lines = rows.map((row) => {
    const rec = row["record"] as Record<string, unknown>;
    return [row["domain_id"], rec["sequence"], rec["operation"], rec["kind"]].join(",");
  });
  return ["domain_id,sequence,operation,kind", ...lines].join("\n") + "\n";
}

function audit(ctx: FeatureMockContext, rest: string): void {
  if (ctx.req.method !== "GET") return json(ctx, 405, { error: "method not allowed" });
  if (rest === "/siem/status") {
    return json(ctx, 200, {
      sink: "eventhubs",
      state: "ok",
      reason: null,
      total_sent: 120,
      total_failures: 3,
      consecutive_failures: 0,
      last_success_at: "2026-11-02T07:59:00Z",
      last_failure_at: "2026-11-01T03:00:00Z",
      last_failure_reason: "sink_timeout",
    });
  }
  if (rest === "/denials") {
    const denied = allRows().filter((r) => (r["record"] as { kind: string }).kind === "denied");
    return json(ctx, 200, { items: denied.map((r) => r["record"]), next_cursor: null });
  }
  const bad = rangeError(ctx);
  if (rest === "/search") {
    if (bad !== undefined) return problem(ctx, 422, "invalid_schema", bad);
    const rows = filterRows(ctx, allRows());
    const start = Number(ctx.url.searchParams.get("cursor") ?? 0);
    const size = Math.min(Number(ctx.url.searchParams.get("page_size") ?? 50), 200);
    const next = start + size;
    return json(ctx, 200, {
      items: rows.slice(start, next),
      domains: [ADMIN_DOMAIN_FINANCE, ADMIN_DOMAIN_PEOPLE],
      next_cursor: next < rows.length ? String(next) : null,
    });
  }
  if (rest === "/export") {
    if (ctx.role !== "admin") return problem(ctx, 403, "forbidden", "permission_missing");
    if (bad !== undefined) return problem(ctx, 422, "invalid_schema", bad);
    const rows = filterRows(ctx, allRows());
    const csv = ctx.url.searchParams.get("format") === "csv";
    const text = csv
      ? csvOf(rows)
      : rows.map((r) => JSON.stringify(r["record"] as object)).join("\n") + "\n";
    return json(
      ctx,
      200,
      text,
      {
        "content-type": csv ? "text/csv; charset=utf-8" : "application/x-ndjson",
        "content-disposition": `attachment; filename="audit-export.${csv ? "csv" : "ndjson"}"`,
        "x-neurosphere-export-rows": String(rows.length),
        "x-neurosphere-export-truncated": "false",
        "access-control-expose-headers":
          "x-correlation-id, etag, content-disposition, x-neurosphere-export-rows, x-neurosphere-export-truncated",
      },
      csv ? "text/csv; charset=utf-8" : "application/x-ndjson",
    );
  }
  return problem(ctx, 404, "not_found", "unknown_route");
}

export const handle: FeatureMockHandler = (ctx) => {
  // The registry test passes an empty context; a handler must pass on anything it cannot read.
  const requestUrl = (ctx as { url?: URL }).url;
  if (requestUrl === undefined) return false;
  const path = requestUrl.pathname;
  const isIdentity = path === IDENTITY || path.startsWith(`${IDENTITY}/`);
  const isDomains = path === PLATFORM_DOMAINS || path.startsWith(`${PLATFORM_DOMAINS}/`);
  const isSystem = path.startsWith(`${SYSTEM}/`);
  const auditRest = ["/search", "/export", "/denials", "/siem/status"].find(
    (suffix) => path === `${AUDIT}${suffix}`,
  );
  if (!isIdentity && !isDomains && !isSystem && auditRest === undefined) return false;
  if (!ctx.authorized) {
    json(ctx, 401, { error: "missing or unrecognised token" });
    return true;
  }
  const allowed =
    auditRest === undefined ? ctx.role === "admin" : ctx.role === "admin" || ctx.role === "auditor";
  if (!allowed) {
    problem(ctx, 403, "forbidden", "deployment_scope_required");
    return true;
  }
  if (isIdentity) void identity(ctx, path.slice(IDENTITY.length));
  else if (isDomains) void platformDomains(ctx, path.slice(PLATFORM_DOMAINS.length));
  else if (isSystem) system(ctx, path.slice(SYSTEM.length));
  else audit(ctx, auditRest ?? "");
  return true;
};
