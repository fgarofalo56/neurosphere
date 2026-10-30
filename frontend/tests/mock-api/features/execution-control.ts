import type { FeatureMockContext, FeatureMockHandler } from "./context.ts";

/**
 * PRP-31 item 8 execution-control mock: GET/PUT /api/v1/actions/emergency-disable. It takes over
 * both methods (registry modules dispatch before server.ts's GET-only actions handler), so the
 * /actions banner and /admin/execution-control read one state. Like the API, a read needs any
 * valid token while a write needs config.manage, stood in for by the Admin role. State is
 * module-level and SYNTHETIC; a spec that disables must enable again.
 */

export const EMERGENCY_DISABLE_PATH = "/api/v1/actions/emergency-disable";
export const CONTROL_ACTOR = "psn-mock-admin";

const REASON = /^[a-z][a-z0-9_]{0,63}$/;

interface View {
  disabled: boolean;
  reason: string | null;
  changed_by: string | null;
  changed_at: string | null;
}

let view: View = { disabled: false, reason: null, changed_by: null, changed_at: null };

export function resetExecutionControl(): void {
  view = { disabled: false, reason: null, changed_by: null, changed_at: null };
}

function json(ctx: FeatureMockContext, status: number, body: unknown, type = "application/json") {
  ctx.res.writeHead(status, { "content-type": type, ...ctx.cors });
  ctx.res.end(JSON.stringify(body));
}

function problem(ctx: FeatureMockContext, status: number, code: string, detail: string): void {
  json(
    ctx,
    status,
    {
      schema_version: "1.0.0",
      type: `https://neurosphere.invalid/problems/${code.replaceAll("_", "-")}`,
      title: status === 403 ? "Forbidden" : "Invalid request",
      status,
      detail,
      instance: EMERGENCY_DISABLE_PATH,
      code,
      reason: detail,
      retryable: false,
      correlation_id: ctx.correlationId,
    },
    "application/problem+json",
  );
}

function readBody(ctx: FeatureMockContext): Promise<unknown> {
  return new Promise((resolve) => {
    let raw = "";
    ctx.req.on("data", (chunk: Buffer) => {
      raw += chunk.toString("utf8");
    });
    ctx.req.on("end", () => {
      try {
        resolve(JSON.parse(raw) as unknown);
      } catch {
        resolve(undefined);
      }
    });
  });
}

async function put(ctx: FeatureMockContext): Promise<void> {
  if (ctx.role !== "admin") {
    problem(ctx, 403, "forbidden", "permission_missing");
    return;
  }
  const body = (await readBody(ctx)) as { disabled?: unknown; reason?: unknown } | undefined;
  const reason = body?.reason ?? null;
  const reasonOk = reason === null || (typeof reason === "string" && REASON.test(reason));
  if (typeof body?.disabled !== "boolean" || !reasonOk || (body.disabled && reason === null)) {
    problem(ctx, 422, "invalid_schema", "disabling execution requires a reason code");
    return;
  }
  view = {
    disabled: body.disabled,
    reason: reason as string | null,
    changed_by: CONTROL_ACTOR,
    changed_at: "2026-10-30T12:00:00.000000Z",
  };
  json(ctx, 200, view);
}

export const handle: FeatureMockHandler = (ctx) => {
  // The registry test passes an empty context; a handler must pass on anything it cannot read.
  const requestUrl = (ctx as { url?: URL }).url;
  if (requestUrl === undefined) return false;
  if (requestUrl.pathname !== EMERGENCY_DISABLE_PATH) return false;
  if (!ctx.authorized) {
    json(ctx, 401, { error: "missing or unrecognised token" });
    return true;
  }
  if (ctx.req.method === "GET") {
    json(ctx, 200, view);
    return true;
  }
  if (ctx.req.method === "PUT") {
    void put(ctx);
    return true;
  }
  json(ctx, 405, { error: "method not allowed" });
  return true;
};
