import type { FeatureMockContext, FeatureMockHandler } from "./context.ts";

/**
 * PRP-139 item 4 mock: the source status routes of PRP-139 item 3.
 *
 * - `GET /api/v1/sources/status` answers the four sources (any principal that can read a domain).
 * - `GET /api/v1/admin/sources/status` adds `reason` and the per-kind run status (admin persona
 *   only, others get 403).
 *
 * The default world HAS data: the four connectable sources are `connected` with a recent
 * `last_success_at`, so other pages keep their usual look. A spec that wants another world
 * calls `setSourceStatusWorld`. Every value is SYNTHETIC; no id, host or token appears.
 */

export const SOURCES_STATUS_USER_PATH = "/api/v1/sources/status";
export const SOURCES_STATUS_ADMIN_PATH = "/api/v1/admin/sources/status";

export type SourceStatusWorld = "has_data" | "none_connected" | "access_denied";

const RECENT = "2026-11-20T09:00:00Z";

type SourceName = "foundry" | "apim_gateway" | "billing" | "azure_monitor_telemetry";
type ConnectorKind = "foundry_discovery" | "gateway_poll" | "billing_export" | "azure_monitor_ai";

interface SourceRow {
  source: SourceName;
  state: string;
  last_success_at: string | null;
  available: boolean;
  reason: string | null;
}
interface ConnectorRow {
  kind: ConnectorKind;
  state: string;
  reason: string | null;
  last_success_at: string | null;
  last_attempt_at: string | null;
  counts: Record<string, number>;
}

let world: SourceStatusWorld = "has_data";

export function setSourceStatusWorld(next: SourceStatusWorld): void {
  world = next;
}

export function resetSourceStatus(): void {
  world = "has_data";
}

function sources(): SourceRow[] {
  const names: SourceName[] = ["foundry", "apim_gateway", "billing", "azure_monitor_telemetry"];
  if (world === "none_connected") {
    return [
      ...names.map((source) => ({
        source,
        state: "not_connected",
        last_success_at: null,
        available: true,
        reason: null,
      })),
    ];
  }
  return [
    ...names.map((source) => {
      const denied = world === "access_denied" && source === "foundry";
      return {
        source,
        state: denied ? "failing" : "connected",
        last_success_at: denied ? null : RECENT,
        available: true,
        reason: denied ? "source_access_denied" : null,
      };
    }),
  ];
}

function connectors(): ConnectorRow[] {
  if (world === "none_connected") return [];
  const kinds: ConnectorKind[] = [
    "foundry_discovery",
    "gateway_poll",
    "billing_export",
    "azure_monitor_ai",
  ];
  return kinds.map((kind) => {
    const denied = world === "access_denied" && kind === "foundry_discovery";
    return {
      kind,
      state: denied ? "failed" : "ok",
      reason: denied ? "source_access_denied" : null,
      last_success_at: denied ? null : RECENT,
      last_attempt_at: RECENT,
      counts: denied ? {} : { records: 3 },
    };
  });
}

function reply(ctx: FeatureMockContext, status: number, body: unknown): void {
  ctx.res.writeHead(status, { "content-type": "application/json", ...ctx.cors });
  ctx.res.end(JSON.stringify(body));
}

export const handle: FeatureMockHandler = (ctx) => {
  // The registry test passes an empty context; a handler must pass on anything it cannot read.
  const url = (ctx as { url?: URL }).url;
  if (url === undefined) return false;
  const admin = url.pathname === SOURCES_STATUS_ADMIN_PATH;
  if (!admin && url.pathname !== SOURCES_STATUS_USER_PATH) return false;
  if (!ctx.authorized) {
    reply(ctx, 401, { error: "missing or unrecognised token" });
    return true;
  }
  if (admin) {
    if (ctx.role !== "admin") {
      ctx.problem(403, "forbidden", "permission_missing", "this operation needs `config.manage`");
      return true;
    }
    reply(ctx, 200, { sources: sources(), connectors: connectors() });
    return true;
  }
  if (ctx.readableDomains.length === 0) {
    ctx.forbidden();
    return true;
  }
  reply(ctx, 200, {
    sources: sources().map((row) => ({
      source: row.source,
      state: row.state,
      last_success_at: row.last_success_at,
      available: row.available,
    })),
  });
  return true;
};
