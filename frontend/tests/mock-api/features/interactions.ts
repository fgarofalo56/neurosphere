import type { FeatureMockContext, FeatureMockHandler } from "./context.ts";

/**
 * PRP-104 item 6 mock: the interaction explorer routes under `/api/v1/domains/{d}/`.
 *
 * - `GET .../interactions` (data.read) lists three synthetic records; filters `agent_id`,
 *   `principal_id`, `tool_id`, `data_asset_id` and `detected_category` narrow the list, and
 *   `page_size` below 3 pages through an opaque `continuation`.
 * - `GET .../interactions/{id}` answers one record, or 404 `interaction_not_found`.
 * - `POST .../interactions/{id}/content-reads` returns the synthetic redacted content to the
 *   `investigator` persona only (403 for every other persona, admin included); a missing or
 *   unknown purpose or a GUID-shaped case reference is 422 `interaction_purpose_invalid`.
 * - `POST .../interaction-exports` (investigator only) answers 201 with a manifest; the case
 *   reference `case-e2e-limit` stands in for a 6th open export (429 with `Retry-After`).
 * - `GET .../interaction-exports/{id}` and `/bundle` answer an export this server created.
 *
 * Only the readable fixture domain answers; any other domain is 403. Every value is SYNTHETIC:
 * placeholder text only, no personal data, key, token or card number.
 */

export const INTERACTION_DOMAIN = "commercial:e2e:sandbox:domain:finance";
export const INTERACTION_ID = "1a1a1a1a-0000-4000-8000-000000000001";
export const INTERACTION_CLEAN = "1a1a1a1a-0000-4000-8000-000000000002";
export const INTERACTION_FAILED = "1a1a1a1a-0000-4000-8000-000000000003";
export const INTERACTION_AGENT = "commercial:e2e:sandbox:agent:support-bot";
export const INVESTIGATOR_ROLE = "investigator";
export const EXPORT_LIMIT_CASE_REF = "case-e2e-limit";
export const EXPORT_RETRY_AFTER_SECONDS = 7200;
export const EXPORT_AUDIT_ID = "2b2b2b2b-0000-4000-8000-000000000001";
export const SYNTHETIC_PROMPT =
  "SYNTHETIC PROMPT PLACEHOLDER: summarise ticket for [[ns-redacted:email_address]]";
export const SYNTHETIC_RESPONSE = "SYNTHETIC RESPONSE PLACEHOLDER: the ticket is summarised.";

const BASE =
  /^\/api\/v1\/domains\/([^/]+)\/(interactions|interaction-exports)(?:\/([^/]+))?(?:\/([^/]+))?$/;
const PURPOSES = new Set([
  "incident_investigation",
  "policy_violation_review",
  "legal_hold_review",
  "data_subject_request",
  "security_review",
  "quality_review",
]);
const CASE_REF = /^[A-Za-z0-9._:-]{1,128}$/;
const GUID = /[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/;
const PRINCIPAL = `commercial:e2e:entra:person:p-${"0".repeat(64)}`;
const HEX64 = "0".repeat(64);

function record(id: string, over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    schema_version: "1.0.0",
    interaction_id: id,
    cloud: "commercial",
    customer_id: "e2e",
    domain_id: INTERACTION_DOMAIN,
    source_id: "src-e2e-chat",
    event_id: `evt-${id.slice(-4)}`,
    trace_id: null,
    span_id: null,
    correlation_id: `corr-e2e-${id.slice(-4)}`,
    capture_source: "edge_push",
    occurred_at: "2026-10-24T09:00:00Z",
    captured_at: "2026-10-24T09:00:01Z",
    agent_id: INTERACTION_AGENT,
    agent_version_id: null,
    tool_id: null,
    service_id: null,
    mcp_server_id: null,
    model: {
      provider: "azure_openai",
      model_name: "e2e-model",
      model_version: "1",
      deployment_id: null,
    },
    principal_id: PRINCIPAL,
    capture_policy_id: "support-capture",
    capture_policy_version: 2,
    detector_set_version: "ns-detectors-1",
    redaction_state: "redacted",
    parts: [
      { part: "prompt", char_count: 80, truncated: false },
      { part: "response", char_count: 56, truncated: false },
    ],
    content_ref: {
      pointer: `content/e2e/${id}`,
      kek_uri: "https://ns-e2e-kv.vault.azure.net/keys/ns-content",
      algorithm: "aes_256_gcm",
      ciphertext_sha256: HEX64,
      byte_length: 512,
    },
    findings_summary: [{ category: "email_address", count: 1, action: "replaced" }],
    sensitivity_categories: [],
    data_asset_ids: ["commercial:e2e:sandbox:dataset:tickets"],
    retention_class: "interaction_default",
    expires_at: "2026-11-23T09:00:01Z",
    legal_hold_ids: [],
    ...over,
  };
}

function records(): Record<string, unknown>[] {
  return [
    record(INTERACTION_ID),
    record(INTERACTION_CLEAN, {
      captured_at: "2026-10-24T08:00:01Z",
      occurred_at: "2026-10-24T08:00:00Z",
      redaction_state: "not_required",
      findings_summary: [],
      tool_id: "commercial:e2e:sandbox:tool:search",
    }),
    record(INTERACTION_FAILED, {
      captured_at: "2026-10-24T07:00:01Z",
      occurred_at: "2026-10-24T07:00:00Z",
      redaction_state: "redaction_failed",
      content_ref: null,
      findings_summary: [],
      agent_id: "commercial:e2e:sandbox:agent:triage-bot",
    }),
  ];
}

function content(id: string): Record<string, unknown> {
  return {
    schema_version: "1.0.0",
    interaction_id: id,
    redaction_state: "redacted",
    detector_set_version: "ns-detectors-1",
    parts: [
      {
        part: "prompt",
        text: SYNTHETIC_PROMPT,
        truncated: false,
        findings: [
          {
            category: "email_address",
            part: "prompt",
            detector_id: "email",
            detector_version: "1.0.0",
            count: 1,
            action: "replaced",
            confidence: "high",
          },
        ],
      },
      { part: "response", text: SYNTHETIC_RESPONSE, truncated: false, findings: [] },
    ],
  };
}

const exportsCreated = new Map<string, Record<string, unknown>>();
let exportSequence = 0;

function reply(ctx: FeatureMockContext, status: number, body: unknown, extra = {}): void {
  ctx.res.writeHead(status, {
    "content-type": "application/json",
    "cache-control": "no-store",
    ...ctx.cors,
    ...extra,
  });
  ctx.res.end(JSON.stringify(body));
}

function matches(r: Record<string, unknown>, url: URL): boolean {
  const eq = (param: string, field: string): boolean => {
    const want = url.searchParams.get(param);
    return want === null || r[field] === want;
  };
  const asset = url.searchParams.get("data_asset_id");
  const category = url.searchParams.get("detected_category");
  const findings = r["findings_summary"] as { category: string }[];
  return (
    eq("agent_id", "agent_id") &&
    eq("principal_id", "principal_id") &&
    eq("tool_id", "tool_id") &&
    (asset === null || (r["data_asset_ids"] as string[]).includes(asset)) &&
    (category === null || findings.some((f) => f.category === category))
  );
}

function search(ctx: FeatureMockContext): void {
  const all = records().filter((r) => matches(r, ctx.url));
  const size = Math.max(
    1,
    Math.min(100, Number(ctx.url.searchParams.get("page_size") ?? 25) || 25),
  );
  const start = Number(ctx.url.searchParams.get("continuation")?.replace(/^page-/, "") ?? 0) || 0;
  const items = all.slice(start, start + size);
  const next = start + size < all.length ? `page-${start + size}` : null;
  reply(ctx, 200, { items, continuation: next });
}

/** The purpose problem reason, or null when the purpose is acceptable. */
function purposeProblem(raw: unknown): string | null {
  if (typeof raw !== "object" || raw === null) return "interaction_purpose_invalid";
  const purpose = raw as Record<string, unknown>;
  if (typeof purpose["purpose_code"] !== "string" || !PURPOSES.has(purpose["purpose_code"])) {
    return "interaction_purpose_invalid";
  }
  const ref = purpose["case_ref"];
  if (ref === null || ref === undefined) return null;
  if (typeof ref !== "string" || !CASE_REF.test(ref) || GUID.test(ref)) {
    return "interaction_purpose_invalid";
  }
  return null;
}

async function body(ctx: FeatureMockContext): Promise<unknown> {
  try {
    return JSON.parse(await ctx.readBody()) as unknown;
  } catch {
    return null;
  }
}

function investigatorOnly(ctx: FeatureMockContext, permission: string): boolean {
  if (ctx.role === INVESTIGATOR_ROLE) return true;
  ctx.problem(403, "forbidden", "permission_denied", `this operation needs \`${permission}\``);
  return false;
}

async function readContent(ctx: FeatureMockContext, id: string): Promise<void> {
  const raw = await body(ctx);
  if (!investigatorOnly(ctx, "interaction.read")) return;
  if (purposeProblem(raw) !== null) {
    ctx.problem(422, "invalid_schema", "interaction_purpose_invalid", "purpose refused");
    return;
  }
  const found = records().find((r) => r["interaction_id"] === id);
  if (found === undefined || found["content_ref"] === null) {
    ctx.problem(404, "not_found", "interaction_not_found", "no such interaction content");
    return;
  }
  reply(ctx, 200, content(id));
}

async function createExport(ctx: FeatureMockContext): Promise<void> {
  const raw = (await body(ctx)) as Record<string, unknown> | null;
  if (!investigatorOnly(ctx, "interaction.export")) return;
  const purpose = raw?.["purpose"];
  if (purposeProblem(purpose) !== null) {
    ctx.problem(422, "invalid_schema", "interaction_purpose_invalid", "purpose refused");
    return;
  }
  const filters = (raw?.["filters"] ?? null) as Record<string, unknown> | null;
  if (
    filters === null ||
    typeof filters["from"] !== "string" ||
    typeof filters["to"] !== "string"
  ) {
    ctx.problem(422, "invalid_schema", "interaction_export_filters_invalid", "filters refused");
    return;
  }
  if ((purpose as Record<string, unknown>)["case_ref"] === EXPORT_LIMIT_CASE_REF) {
    reply(
      ctx,
      429,
      {
        schema_version: "1.0.0",
        type: "https://neurosphere.invalid/problems/rate-limited",
        title: "Rate limited",
        status: 429,
        detail: "at most 5 open exports per investigator",
        instance: ctx.url.pathname,
        code: "rate_limited",
        reason: "interaction_export_limit_reached",
        // The real API says retryable; false here keeps the shared client from waiting in e2e.
        retryable: false,
        retry_after_seconds: EXPORT_RETRY_AFTER_SECONDS,
        correlation_id: ctx.correlationId,
      },
      { "retry-after": String(EXPORT_RETRY_AFTER_SECONDS) },
    );
    return;
  }
  exportSequence += 1;
  const exportId = `3c3c3c3c-0000-4000-8000-${String(exportSequence).padStart(12, "0")}`;
  const ids = [INTERACTION_ID, INTERACTION_CLEAN];
  const manifest = {
    schema_version: "1.0.0",
    export_id: exportId,
    cloud: "commercial",
    customer_id: "e2e",
    domain_ids: [INTERACTION_DOMAIN],
    requested_by: PRINCIPAL,
    requested_at: "2026-10-24T12:00:00Z",
    purpose,
    filters: { agent_ids: [], detected_categories: [], ...filters },
    interaction_count: ids.length,
    interaction_ids: ids,
    excluded_count: 1,
    includes_held_content: false,
    bundle: {
      pointer: `exports/e2e/${exportId}/bundle`,
      kek_uri: "https://ns-e2e-kv.vault.azure.net/keys/ns-content",
      algorithm: "aes_256_gcm",
      ciphertext_sha256: HEX64,
      byte_length: 2048,
    },
    audit_id: EXPORT_AUDIT_ID,
    expires_at: "2026-10-25T12:00:00Z",
  };
  exportsCreated.set(exportId, manifest);
  reply(ctx, 201, manifest);
}

function readExport(ctx: FeatureMockContext, exportId: string, bundle: boolean): void {
  if (!investigatorOnly(ctx, "interaction.export")) return;
  const manifest = exportsCreated.get(exportId);
  if (manifest === undefined) {
    ctx.problem(404, "not_found", "interaction_export_not_found", "no such export");
    return;
  }
  if (!bundle) {
    reply(ctx, 200, manifest);
    return;
  }
  const ids = manifest["interaction_ids"] as string[];
  reply(
    ctx,
    200,
    {
      format: "ns-interaction-export-bundle-1",
      export_id: exportId,
      customer_id: "e2e",
      domain_id: INTERACTION_DOMAIN,
      interactions: Object.fromEntries(ids.map((id) => [id, content(id)])),
    },
    { "content-disposition": `attachment; filename="interaction-export-${exportId}.json"` },
  );
}

export const handle: FeatureMockHandler = (ctx) => {
  // The registry test passes an empty context; a handler must pass on anything it cannot read.
  const url = (ctx as { url?: URL }).url;
  if (url === undefined) return false;
  const match = BASE.exec(url.pathname);
  if (match === null) return false;
  const [, rawDomain = "", kind = "", id, tail] = match;
  const method = ctx.req.method ?? "GET";
  if (!ctx.authorized) {
    reply(ctx, 401, { error: "missing or unrecognised token" });
    return true;
  }
  if (decodeURIComponent(rawDomain) !== INTERACTION_DOMAIN) {
    ctx.forbidden();
    return true;
  }
  if (kind === "interactions") {
    if (id === undefined && method === "GET") {
      search(ctx);
      return true;
    }
    if (id !== undefined && tail === undefined && method === "GET") {
      const found = records().find((r) => r["interaction_id"] === id);
      if (found === undefined) {
        ctx.problem(404, "not_found", "interaction_not_found", "no such interaction");
      } else {
        reply(ctx, 200, found);
      }
      return true;
    }
    if (id !== undefined && tail === "content-reads" && method === "POST") {
      void readContent(ctx, id);
      return true;
    }
  } else {
    if (id === undefined && method === "POST") {
      void createExport(ctx);
      return true;
    }
    if (id !== undefined && method === "GET" && (tail === undefined || tail === "bundle")) {
      readExport(ctx, id, tail === "bundle");
      return true;
    }
  }
  ctx.problem(405, "method_not_allowed", undefined, "method not allowed on this route");
  return true;
};
