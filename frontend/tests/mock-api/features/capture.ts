import type { FeatureMockContext, FeatureMockHandler } from "./context.ts";

/**
 * PRP-103 item 5 mock: the read-only capture admin routes.
 *
 * - `GET /api/v1/admin/interactions/capture-policies` lists two synthetic policies.
 * - `GET /api/v1/admin/interactions/capture-policies/{policy_id}` answers one, or 404.
 * - `GET /api/v1/admin/interactions/capture-status` says capture is off (`setting_off`).
 *
 * The admin persona only (the API needs customer-level `config.manage`); any other persona gets
 * 403 `customer_scope_required`. Any other method is 405: there is no write route. Every value is
 * SYNTHETIC; no content, key, host or token appears.
 */

export const CAPTURE_API = "/api/v1/admin/interactions";
export const CAPTURE_POLICY_ID = "support-capture";
export const CAPTURE_APPROVAL_AUDIT_ID = "approval-audit-e2e-1";

const DOMAIN = "commercial:e2e:catalog:domain:support";

function policy(id: string, over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    policy_id: id,
    display_name: "Support capture",
    version: 2,
    previous_version: 1,
    domain_id: DOMAIN,
    source_ids: ["src-e2e-chat"],
    parts: ["prompt", "response"],
    detector_set_version: "ns-detectors-1",
    customer_dictionary_ids: [],
    redaction_mode: "redact_all_detections",
    kept_categories: [],
    sampling: { rate: 0.5, max_per_minute: 120 },
    max_part_chars: 8192,
    retention_class: "interaction_default",
    retention_days: 30,
    state: "active",
    approved_intent_id: "intent-e2e-1",
    approved_audit_id: CAPTURE_APPROVAL_AUDIT_ID,
    effective_from: "2026-11-21T08:00:00Z",
    ...over,
  };
}

function policies(): Record<string, unknown>[] {
  return [
    policy(CAPTURE_POLICY_ID),
    policy("triage-capture", {
      display_name: "Triage capture",
      state: "proposed",
      version: 1,
      previous_version: null,
      approved_intent_id: null,
      approved_audit_id: null,
      effective_from: null,
    }),
  ];
}

function status(): Record<string, unknown> {
  return {
    state: "off",
    off_reason: "setting_off",
    configured: true,
    domain_id: null,
    policies: { total: 2, proposed: 1, active: 1, suspended: 0, retired: 0 },
    policies_truncated: false,
    counters: null,
    counters_scope: "customer",
  };
}

function reply(ctx: FeatureMockContext, status: number, body: unknown): void {
  ctx.res.writeHead(status, { "content-type": "application/json", ...ctx.cors });
  ctx.res.end(JSON.stringify(body));
}

export const handle: FeatureMockHandler = (ctx) => {
  // The registry test passes an empty context; a handler must pass on anything it cannot read.
  const url = (ctx as { url?: URL }).url;
  if (url === undefined) return false;
  const path = url.pathname;
  if (!path.startsWith(`${CAPTURE_API}/capture-`)) return false;
  if (ctx.req.method !== "GET") {
    ctx.problem(405, "method_not_allowed", undefined, "this route is read-only");
    return true;
  }
  if (!ctx.authorized) {
    reply(ctx, 401, { error: "missing or unrecognised token" });
    return true;
  }
  if (ctx.role !== "admin") {
    ctx.problem(
      403,
      "forbidden",
      "customer_scope_required",
      "every domain needs customer-level config.manage; name a domain_id",
    );
    return true;
  }
  if (path === `${CAPTURE_API}/capture-status`) {
    reply(ctx, 200, status());
    return true;
  }
  if (path === `${CAPTURE_API}/capture-policies`) {
    reply(ctx, 200, { items: policies(), truncated: false, configured: true, reason: null });
    return true;
  }
  const prefix = `${CAPTURE_API}/capture-policies/`;
  if (path.startsWith(prefix)) {
    const id = decodeURIComponent(path.slice(prefix.length));
    const found = policies().find((p) => p.policy_id === id);
    if (found === undefined) {
      ctx.problem(404, "not_found", "capture_policy_not_found", "capture policy not found");
    } else {
      reply(ctx, 200, found);
    }
    return true;
  }
  return false;
};
