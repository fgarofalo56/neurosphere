import type { FeatureMockContext, FeatureMockHandler } from "./context.ts";

/**
 * PRP-31 item 5 audit mock: GET /api/v1/audit/domains, /{domain}/records, /{domain}/verify.
 * Shapes follow services/api/neurosphere_api/ui_adapters/audit.py. Every identity, hash and
 * timestamp is SYNTHETIC. Like the real adapter, only Auditor and Admin tokens may read (the
 * audit.read stand-in); the mock never looks at `/me/domains`.
 */

export const AUDIT_DOMAINS_PATH = "/api/v1/audit/domains";
const DOMAIN_PATH = /^\/api\/v1\/audit\/domains\/([^/]+)\/(records|verify)$/;

export const AUDIT_DOMAIN_FINANCE = "commercial:e2e:catalog:domain:finance";
export const AUDIT_DOMAIN_HR = "commercial:e2e:catalog:domain:people";
export const AUDIT_DOMAIN_EMPTY = "commercial:e2e:catalog:domain:archive";
export const AUDIT_DOMAIN_UNCONFIGURED = "commercial:e2e:catalog:domain:offline";

/** Records in the finance chain: more than one page at the page size the UI asks for. */
export const AUDIT_FINANCE_COUNT = 30;
/** The people chain is intentionally broken for the verify path. */
export const AUDIT_HR_COUNT = 4;
export const AUDIT_HR_BREAK_SEQUENCE = 2;

const DOMAINS = [
  { domain_id: AUDIT_DOMAIN_FINANCE, display_name: "Finance", display_name_source: "catalog" },
  { domain_id: AUDIT_DOMAIN_HR, display_name: "People", display_name_source: "derived" },
  { domain_id: AUDIT_DOMAIN_EMPTY, display_name: "Archive", display_name_source: "derived" },
  { domain_id: AUDIT_DOMAIN_UNCONFIGURED, display_name: "Offline", display_name_source: "derived" },
] as const;

const HEX = "0123456789abcdef";
function hash(seed: number): string {
  let out = "sha256:";
  for (let i = 0; i < 64; i += 1) out += HEX[(seed * 7 + i * 5 + (i >> 2)) % 16];
  return out;
}

function chainId(domain: string): string {
  const name = domain.split(":").pop() ?? "x";
  return `e2e.${name}`;
}

function uuid(seed: number): string {
  const tail = seed.toString(16).padStart(12, "0");
  return `00000000-0000-4000-8000-${tail}`;
}

function record(domain: string, sequence: number): Record<string, unknown> {
  const kind = sequence % 3 === 2 ? "denied" : sequence % 3 === 0 ? "before" : "after";
  const minute = String(sequence % 60).padStart(2, "0");
  return {
    schema_version: "1.0.0",
    audit_id: uuid(sequence + 1),
    chain_id: chainId(domain),
    sequence,
    previous_hash: sequence === 0 ? null : hash(sequence - 1),
    record_hash: hash(sequence),
    kind,
    recorded_at: `2026-10-20T10:${minute}:00.000000Z`,
    actor: {
      principal_pseudonym: `psn-mock-actor-${sequence % 4}`,
      principal_kind: "user",
      on_behalf_of: null,
    },
    scope_hash: hash(900),
    correlation_id: `corr-audit-${sequence}`,
    operation: kind === "denied" ? "graph.query" : "action.execute",
    channel: sequence % 5 === 0 ? null : sequence % 2 === 0 ? "button" : "rest",
    intent_id: null,
    subject:
      kind === "denied"
        ? null
        : {
            target: {
              canonical_id: `commercial:e2e:catalog:model_deployment:dep-${sequence}`,
              entity_type: "model_deployment",
            },
            target_version: `v${sequence + 1}`,
            state_digest: hash(sequence + 300),
            snapshot_ref: null,
          },
    outcome: kind === "after" ? { result: "succeeded", verified: true, detail: null } : null,
    denial: kind === "denied" ? { code: "forbidden", reason: "domain_out_of_scope" } : null,
  };
}

function count(domain: string): number {
  if (domain === AUDIT_DOMAIN_FINANCE) return AUDIT_FINANCE_COUNT;
  if (domain === AUDIT_DOMAIN_HR) return AUDIT_HR_COUNT;
  return 0;
}

function json(ctx: FeatureMockContext, status: number, body: unknown, type = "application/json") {
  ctx.res.writeHead(status, { "content-type": type, ...ctx.cors });
  ctx.res.end(JSON.stringify(body));
}

function problem(
  ctx: FeatureMockContext,
  status: number,
  code: string,
  reason: string,
  retryable: boolean,
): void {
  json(
    ctx,
    status,
    {
      schema_version: "1.0.0",
      type: `https://neurosphere.invalid/problems/${code.replaceAll("_", "-")}`,
      title: status === 503 ? "Audit store unavailable" : "Forbidden",
      status,
      detail: reason,
      instance: ctx.url.pathname,
      code,
      reason,
      retryable,
      correlation_id: ctx.correlationId,
    },
    "application/problem+json",
  );
}

export const handle: FeatureMockHandler = (ctx) => {
  // The registry test passes an empty context; a handler must pass on anything it cannot read.
  const requestUrl = (ctx as { url?: URL }).url;
  if (requestUrl === undefined) return false;
  const path = requestUrl.pathname;
  const match = DOMAIN_PATH.exec(path);
  if (path !== AUDIT_DOMAINS_PATH && match === null) return false;
  if (ctx.req.method !== "GET") {
    json(ctx, 405, { error: "method not allowed" });
    return true;
  }
  if (!ctx.authorized) {
    json(ctx, 401, { error: "missing or unrecognised token" });
    return true;
  }
  if (ctx.role !== "auditor" && ctx.role !== "admin") {
    problem(ctx, 403, "forbidden", "permission_missing", false);
    return true;
  }
  if (match === null) {
    json(ctx, 200, { items: DOMAINS });
    return true;
  }
  const domain = decodeURIComponent(match[1] ?? "");
  if (!DOMAINS.some((d) => d.domain_id === domain)) {
    problem(ctx, 403, "forbidden", "audit_chain_out_of_scope", false);
    return true;
  }
  if (domain === AUDIT_DOMAIN_UNCONFIGURED) {
    problem(ctx, 503, "dependency_transient", "audit_store_unconfigured", false);
    return true;
  }
  const total = count(domain);
  if (match[2] === "verify") {
    const broken = domain === AUDIT_DOMAIN_HR;
    json(ctx, 200, {
      chain_id: chainId(domain),
      ok: !broken,
      records_checked: broken ? AUDIT_HR_BREAK_SEQUENCE + 1 : total,
      first_invalid_index: broken ? AUDIT_HR_BREAK_SEQUENCE : null,
      first_invalid_sequence: broken ? AUDIT_HR_BREAK_SEQUENCE : null,
      reason: broken ? "record_hash_mismatch" : null,
    });
    return true;
  }
  const cursor = ctx.url.searchParams.get("cursor");
  const start = cursor === null ? 0 : Number(cursor);
  const size = Math.min(Number(ctx.url.searchParams.get("page_size") ?? 50), 200);
  if (!Number.isInteger(start) || start < 0 || !Number.isInteger(size) || size < 1) {
    problem(ctx, 422, "invalid_schema", "invalid_cursor", false);
    return true;
  }
  const items: Record<string, unknown>[] = [];
  for (let s = start; s < Math.min(total, start + size); s += 1) items.push(record(domain, s));
  const next = start + size;
  json(ctx, 200, { items, next_cursor: next < total ? String(next) : null });
  return true;
};
