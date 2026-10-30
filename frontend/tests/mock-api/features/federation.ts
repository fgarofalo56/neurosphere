import type { FeatureMockHandler } from "./context.ts";

/**
 * PRP-31 item 6 mock: `GET /api/v1/federation/summary`. Synthetic data only. With no `cells`
 * filter three cells answer (ok, denied, unavailable), so the merged summary is incomplete and
 * carries totals in two currencies. A `cells=cell-a` filter answers a complete summary;
 * `days` above 60 sets `truncated`.
 */
const SUMMARY_PATH = "/api/v1/federation/summary";
const CELLS = [
  { cell_id: "cell-a", state: "ok" },
  { cell_id: "cell-b", state: "denied" },
  { cell_id: "cell-c", state: "unavailable" },
] as const;

export const handle: FeatureMockHandler = (ctx) => {
  // Registry tests pass an empty context to prove placeholders stay inert; stay inert too.
  const url = (ctx as { url?: URL }).url;
  if (url === undefined || url.pathname !== SUMMARY_PATH || ctx.req.method !== "GET") return false;
  const days = Number(url.searchParams.get("days") ?? "30");
  if (!Number.isInteger(days) || days < 1 || days > 90) {
    ctx.problem(422, "invalid_request", undefined, "days must be 1-90");
    return true;
  }
  const wanted = url.searchParams.getAll("cells");
  const cells = wanted.length === 0 ? CELLS : CELLS.filter((c) => wanted.includes(c.cell_id));
  const complete = cells.every((c) => c.state === "ok");
  const end = Date.UTC(2026, 9, 15);
  const body = {
    cloud: "commercial",
    boundary_id: "boundary-sandbox",
    customer_id: "customer-sandbox",
    window_start: new Date(end - days * 86_400_000).toISOString(),
    window_end: new Date(end).toISOString(),
    cells,
    domains: [
      {
        domain_id: "commercial:e2e:sandbox:domain:finance",
        request_count: 1200,
        error_count: 12,
        unknown_outcome_count: null,
        costs: [
          { kind: "estimated", currency: "USD", amount: "410.50", complete: true },
          { kind: "invoiced", currency: "USD", amount: null, complete: false },
        ],
        complete: true,
      },
      {
        domain_id: "commercial:e2e:sandbox:domain:ops",
        request_count: null,
        error_count: null,
        unknown_outcome_count: null,
        costs: [{ kind: "estimated", currency: "EUR", amount: "88.00", complete: false }],
        complete: false,
      },
    ],
    totals: [
      { kind: "estimated", currency: "USD", amount: "410.50", complete: true },
      { kind: "invoiced", currency: "USD", amount: null, complete: false },
      { kind: "estimated", currency: "EUR", amount: "88.00", complete: false },
    ],
    complete,
    truncated: days > 60,
  };
  ctx.res.writeHead(200, { "content-type": "application/json", ...ctx.cors });
  ctx.res.end(JSON.stringify(body));
  return true;
};
