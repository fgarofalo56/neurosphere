/**
 * Tiny Node mock API for Playwright (C10). No network beyond loopback, no
 * credentials: the "token" is an obviously fake string minted by the e2e MSAL
 * stub (tests/e2e-support/stubMsal.ts).
 *
 * It only imitates the authorization *outcome* the real API (PRP-06) owns: a
 * persona workspace answers 200 when the caller's fake token carries the
 * matching role and a 403 ProblemDetails otherwise. The UI never decides.
 *
 * Run directly with Node 24 (native type stripping): node tests/mock-api/server.ts
 */
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { fileURLToPath } from "node:url";
import type { ProblemDetails } from "@neurosphere/contracts";

export const DEFAULT_PORT = 4010;
export const FAKE_TOKEN_PREFIX = "ns-e2e-fake-token.";
const PERSONAS = ["viewer", "analyst", "steward", "admin", "auditor"] as const;
const WORKSPACE_PATH = /^\/api\/v1\/workspaces\/([^/]+)\/?$/;

export interface MockApiOptions {
  /** Origin of the web app under test; echoed back for CORS. */
  readonly allowedOrigin: string;
  /** Base URL the mock tells the app to use (config.json apiBaseUrl). */
  readonly apiBaseUrl: string;
}

function problem(correlationId: string, instance: string): ProblemDetails {
  return {
    schema_version: "1.0.0",
    type: "https://neurosphere.invalid/problems/forbidden",
    title: "Forbidden",
    status: 403,
    detail: "The caller is not permitted to use this workspace.",
    instance,
    code: "forbidden",
    retryable: false,
    correlation_id: correlationId,
  };
}

/** Role carried by the fake token ("ns-e2e-fake-token.Viewer"), lower-cased, or undefined. */
export function roleFromAuthorization(header: string | undefined): string | undefined {
  if (header === undefined || !header.startsWith("Bearer ")) return undefined;
  const token = header.slice("Bearer ".length).trim();
  if (!token.startsWith(FAKE_TOKEN_PREFIX)) return undefined;
  const role = token.slice(FAKE_TOKEN_PREFIX.length).toLowerCase();
  return role === "" ? undefined : role;
}

/** The runtime config.json the e2e app must receive (apiBaseUrl points at this server). */
export function mockPublicConfig(apiBaseUrl: string): Record<string, string> {
  return {
    cloud: "commercial",
    tenantId: "00000000-0000-0000-0000-000000000000",
    clientId: "00000000-0000-0000-0000-000000000000",
    apiBaseUrl,
    apiScope: "api://neurosphere-e2e/access_as_user",
  };
}

// ---- PRP-14 fixtures: GET /api/v1/dashboards/domains/{domain}/{metric} and
// GET /api/v1/reconciliation/domains/{domain}. Shapes follow the contract (Wire contract plus
// the item 4 per-currency references); the numbers are synthetic. The mock only imitates the
// authorization OUTCOME: a domain the stub caller cannot read answers 403, never an empty 200.
const DASHBOARD_PATH =
  /^\/api\/v1\/dashboards\/domains\/([^/]+)\/(cost|latency|errors|coverage)\/?$/;
const RECONCILIATION_PATH = /^\/api\/v1\/reconciliation\/domains\/([^/]+)\/?$/;

/** Domains the stub caller may read. Any other domain id is forbidden (fail closed). */
export const DOMAIN_OK = "commercial:e2e:sandbox:domain:finance";
/** Readable, but the batch analytics backend is disabled; hot aggregates keep serving. */
export const DOMAIN_ANALYTICS_DOWN = "commercial:e2e:sandbox:domain:analytics-down";
/** Not readable by the stub caller: 403 on every dashboards and reconciliation route. */
export const DOMAIN_FORBIDDEN = "commercial:e2e:sandbox:domain:forbidden";
export const ANALYTICS_DISABLED_REASON =
  "no analytics adapter is available for this cloud and region (capability matrix)";
export const ESTIMATED_PRICE_VERSION = {
  id: "sandbox-prices-2026-10",
  effective_date: "2026-10-01",
};
export const INVOICED_PRICE_VERSION = {
  id: "invoice-prices-2026-09",
  effective_date: "2026-09-01",
};
export const FIXTURE_LAG_SECONDS = 120;
export const FIXTURE_WATERMARK = "2026-10-04T21:17:05Z";

interface FixtureValue {
  value: number | null;
  status: "known" | "unknown";
  complete: boolean;
  price_version: { id: string; effective_date: string } | null;
}

const UNKNOWN_VALUE: FixtureValue = {
  value: null,
  status: "unknown",
  complete: false,
  price_version: null,
};

function known(
  value: number,
  complete = true,
  priceVersion: FixtureValue["price_version"] = null,
): FixtureValue {
  return { value, status: "known", complete, price_version: priceVersion };
}

const DAYS = ["2026-10-02T00:00:00Z", "2026-10-03T00:00:00Z", "2026-10-04T00:00:00Z"] as const;

function points(values: readonly FixtureValue[]): { t: string; value: FixtureValue }[] {
  return values.map((value, index) => ({ t: DAYS[index] ?? DAYS[0], value }));
}

function series(
  key: string,
  label: string,
  unit: "currency" | "ms" | "ratio" | "count",
  kind: "estimated" | "invoiced" | null,
  currency: string | null,
  total: FixtureValue,
  values: readonly FixtureValue[],
): Record<string, unknown> {
  return { key, label, kind, unit, currency, total, points: points(values) };
}

function dashboardSeries(metric: string): Record<string, unknown>[] {
  switch (metric) {
    case "cost":
      return [
        // The last day has no known amount: it renders "unknown", never 0, and the total is
        // the partial sum of the known parts with complete=false.
        series(
          "estimated:USD",
          "Cost (estimated, USD)",
          "currency",
          "estimated",
          "USD",
          known(12.5, false, ESTIMATED_PRICE_VERSION),
          [
            known(5, true, ESTIMATED_PRICE_VERSION),
            known(7.5, true, ESTIMATED_PRICE_VERSION),
            { ...UNKNOWN_VALUE },
          ],
        ),
        series(
          "invoiced:USD",
          "Cost (invoiced, USD)",
          "currency",
          "invoiced",
          "USD",
          known(9.25, true, INVOICED_PRICE_VERSION),
          [
            known(4.25, true, INVOICED_PRICE_VERSION),
            known(5, true, INVOICED_PRICE_VERSION),
            known(0, true, INVOICED_PRICE_VERSION),
          ],
        ),
      ];
    case "latency":
      // Percentiles do not combine, so every total is unknown; points may be known.
      return [
        series("p50", "Latency p50", "ms", null, null, { ...UNKNOWN_VALUE }, [
          known(210),
          known(230),
          { ...UNKNOWN_VALUE },
        ]),
        series("p95", "Latency p95", "ms", null, null, { ...UNKNOWN_VALUE }, [
          known(900),
          known(950),
          { ...UNKNOWN_VALUE },
        ]),
        series("p99", "Latency p99", "ms", null, null, { ...UNKNOWN_VALUE }, [
          known(1500),
          known(1600),
          { ...UNKNOWN_VALUE },
        ]),
      ];
    case "errors":
      return [
        series("error_rate", "Error rate", "ratio", null, null, known(0.02, false), [
          known(0.01),
          known(0.03),
          { ...UNKNOWN_VALUE },
        ]),
        series("error_count", "Error count", "count", null, null, known(4, false), [
          known(1),
          known(3),
          { ...UNKNOWN_VALUE },
        ]),
      ];
    default:
      return [
        series("coverage", "Coverage", "ratio", null, null, known(0.75, false), [
          known(1),
          known(0.5),
          known(0.75),
        ]),
      ];
  }
}

function dashboardBody(domain: string, metric: string): Record<string, unknown> {
  const analyticsDown = domain === DOMAIN_ANALYTICS_DOWN;
  return {
    metric,
    domain_id: domain,
    grain: "day",
    window: { start: "2026-10-02T00:00:00Z", end: "2026-10-05T00:00:00Z" },
    freshness: {
      watermark: FIXTURE_WATERMARK,
      lag_seconds: FIXTURE_LAG_SECONDS,
      billing_source_freshness: "2026-10-04T06:00:00Z",
    },
    analytics: analyticsDown
      ? { state: "disabled", reason: ANALYTICS_DISABLED_REASON }
      : { state: "available", reason: null },
    complete: false,
    truncated: false,
    series: dashboardSeries(metric),
    price_versions: metric === "cost" ? [ESTIMATED_PRICE_VERSION, INVOICED_PRICE_VERSION] : [],
  };
}

function reconciliationBody(domain: string): Record<string, unknown> {
  const reference = {
    label: "ledger (one record per request)",
    amount: known(20),
    currency: "USD",
  };
  return {
    domain_id: domain,
    window: { start: "2026-10-02T00:00:00Z", end: "2026-10-05T00:00:00Z" },
    freshness: {
      watermark: FIXTURE_WATERMARK,
      lag_seconds: FIXTURE_LAG_SECONDS,
      billing_source_freshness: "2026-10-04T06:00:00Z",
    },
    complete: false,
    truncated: false,
    reference,
    references: [{ ...reference, entry_count: 12, unknown_entry_count: 3 }],
    sources: [
      {
        source: "gateway",
        granularity: "request",
        amount: known(20),
        coverage: known(0.75, false),
        variance: known(0),
        currency: "USD",
      },
      {
        source: "app",
        granularity: "request",
        amount: known(19.5),
        coverage: known(0.5, false),
        variance: known(-0.5),
        currency: "USD",
      },
      {
        // Vendor-period totals only: no ledger entry was observed by billing, so its coverage is
        // unknown (not 0%), while the vendor-level amount is known.
        source: "billing",
        granularity: "vendor",
        amount: known(18),
        coverage: { ...UNKNOWN_VALUE },
        variance: known(-2),
        currency: "USD",
      },
    ],
    unknown_remainder: { ...known(3), unit: "entries" },
    disclaimer: "not_all_spend_observable",
  };
}

function serveDomainRead(
  res: ServerResponse,
  req: IncomingMessage,
  url: URL,
  domainSegment: string,
  body: (domain: string) => Record<string, unknown>,
  cors: Record<string, string>,
  correlationId: string,
): void {
  if (roleFromAuthorization(req.headers.authorization) === undefined) {
    send(res, 401, { error: "missing or unrecognised token" }, cors);
    return;
  }
  const domain = decodeURIComponent(domainSegment);
  if (domain !== DOMAIN_OK && domain !== DOMAIN_ANALYTICS_DOWN) {
    send(res, 403, problem(correlationId, url.pathname), cors, "application/problem+json");
    return;
  }
  send(res, 200, body(domain), { ...cors, "server-timing": "app;dur=1.0" });
}

function send(
  res: ServerResponse,
  status: number,
  body: unknown,
  headers: Record<string, string>,
  contentType = "application/json",
): void {
  res.writeHead(status, { "content-type": contentType, ...headers });
  res.end(JSON.stringify(body));
}

export function createMockApi(options: MockApiOptions): Server {
  return createServer((req: IncomingMessage, res: ServerResponse) => {
    const correlationId = `e2e-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    const cors: Record<string, string> = {
      "access-control-allow-origin": options.allowedOrigin,
      "access-control-allow-headers": "authorization, content-type, x-correlation-id, if-match",
      "access-control-allow-methods": "GET, OPTIONS",
      "access-control-expose-headers": "x-correlation-id, retry-after",
      vary: "Origin",
      "x-correlation-id": correlationId,
    };
    const url = new URL(req.url ?? "/", "http://mock.invalid");

    if (req.method === "OPTIONS") {
      res.writeHead(204, cors);
      res.end();
      return;
    }
    if (req.method !== "GET") {
      send(res, 405, { error: "method not allowed" }, cors);
      return;
    }
    if (url.pathname === "/api/v1/health") {
      send(res, 200, { status: "ok" }, cors);
      return;
    }
    if (url.pathname === "/config.json") {
      send(res, 200, mockPublicConfig(options.apiBaseUrl), cors);
      return;
    }
    const dashboard = DASHBOARD_PATH.exec(url.pathname);
    if (dashboard !== null) {
      serveDomainRead(
        res,
        req,
        url,
        dashboard[1] ?? "",
        (domain) => dashboardBody(domain, dashboard[2] ?? "cost"),
        cors,
        correlationId,
      );
      return;
    }
    const reconciliation = RECONCILIATION_PATH.exec(url.pathname);
    if (reconciliation !== null) {
      serveDomainRead(
        res,
        req,
        url,
        reconciliation[1] ?? "",
        reconciliationBody,
        cors,
        correlationId,
      );
      return;
    }
    const match = WORKSPACE_PATH.exec(url.pathname);
    if (match !== null) {
      const persona = (match[1] ?? "").toLowerCase();
      if (!(PERSONAS as readonly string[]).includes(persona)) {
        send(res, 404, { error: "unknown workspace" }, cors);
        return;
      }
      const role = roleFromAuthorization(req.headers.authorization);
      if (role === undefined) {
        send(res, 401, { error: "missing or unrecognised token" }, cors);
        return;
      }
      if (role !== persona) {
        send(res, 403, problem(correlationId, url.pathname), cors, "application/problem+json");
        return;
      }
      send(res, 200, { workspace: persona, items: [] }, cors);
      return;
    }
    send(res, 404, { error: "not found" }, cors);
  });
}

const isMain = process.argv[1] !== undefined && fileURLToPath(import.meta.url) === process.argv[1];
if (isMain) {
  const port = Number(process.env["NS_MOCK_API_PORT"] ?? DEFAULT_PORT);
  const appOrigin = process.env["NS_E2E_APP_ORIGIN"] ?? "http://127.0.0.1:4173";
  const server = createMockApi({
    allowedOrigin: appOrigin,
    apiBaseUrl: `http://127.0.0.1:${port}`,
  });
  server.listen(port, "127.0.0.1", () => {
    console.log(`mock api listening on http://127.0.0.1:${port}`);
  });
}
