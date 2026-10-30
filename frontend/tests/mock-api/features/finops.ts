import type { FeatureMockHandler } from "./context.ts";

/**
 * PRP-31 item 6 mock: `GET /api/v1/finops/domains/{d}/forecast`. Synthetic numbers only.
 * USD answers a full forecast with one unknown and one incomplete day; EUR answers "forecast
 * unavailable" for both series; any other currency answers a plain forecast.
 */
const FORECAST_PATH = /^\/api\/v1\/finops\/domains\/([^/]+)\/forecast$/;
const AS_OF = Date.UTC(2026, 9, 15);
const DAY_MS = 86_400_000;

type Amt = {
  value: string | null;
  status: "known" | "unknown";
  complete: boolean;
  reason: string | null;
};

const known = (n: number, complete = true): Amt => ({
  value: n.toFixed(2),
  status: "known",
  complete,
  reason: complete ? null : "partial_day",
});
const unknown = (reason: string): Amt => ({
  value: null,
  status: "unknown",
  complete: false,
  reason,
});
const isoDay = (offset: number): string =>
  new Date(AS_OF + offset * DAY_MS).toISOString().slice(0, 10);

function series(
  kind: "estimated" | "invoiced",
  currency: string,
  historyDays: number,
  horizonDays: number,
  available: boolean,
) {
  const base = kind === "estimated" ? 120 : 100;
  const points: unknown[] = [];
  for (let i = -historyDays; i < 0; i++) {
    let actual = known(base + (i + historyDays) * 1.5 + ((i * 7) % 5));
    if (i === -3) actual = unknown(kind === "estimated" ? "metering_gap" : "invoice_not_posted");
    if (i === -5) actual = known(base * 0.4, false);
    points.push({ day: isoDay(i), phase: "history", actual, forecast: null, within_band: null });
  }
  for (let i = 0; i < horizonDays; i++) {
    const value = base + (historyDays + i) * 1.5;
    points.push({
      day: isoDay(i),
      phase: "horizon",
      actual: unknown("not_yet_billed"),
      forecast: available
        ? {
            value: value.toFixed(2),
            lower: (value - 10 - i).toFixed(2),
            upper: (value + 10 + i).toFixed(2),
          }
        : null,
      within_band: null,
    });
  }
  const sum = (from: number, to: number) => {
    let total = 0;
    for (let i = from; i < to; i++) total += base + (i + historyDays) * 1.5;
    return total;
  };
  return {
    kind,
    currency,
    points,
    summary: {
      history_actual: known(sum(-historyDays, 0) - 90, false),
      horizon_actual: unknown("not_yet_billed"),
      horizon_forecast: available
        ? {
            value: sum(0, horizonDays).toFixed(2),
            lower: (sum(0, horizonDays) - 12 * horizonDays).toFixed(2),
            upper: (sum(0, horizonDays) + 12 * horizonDays).toFixed(2),
          }
        : null,
    },
    forecast_available: available,
    forecast_unavailable_reason: available ? null : "insufficient_complete_history",
    fit_points: available ? historyDays - 2 : 0,
    excluded_incomplete_days: 2,
    residual_std: available ? "3.20" : null,
  };
}

export const handle: FeatureMockHandler = (ctx) => {
  // Registry tests pass an empty context to prove placeholders stay inert; stay inert too.
  const url = (ctx as { url?: URL }).url;
  if (url === undefined) return false;
  const m = FORECAST_PATH.exec(url.pathname);
  if (m === null || ctx.req.method !== "GET") return false;
  const domain = decodeURIComponent(m[1] ?? "");
  if (!ctx.readableDomains.includes(domain)) {
    ctx.forbidden();
    return true;
  }
  const history = Number(url.searchParams.get("history_days") ?? "30");
  const horizon = Number(url.searchParams.get("horizon_days") ?? "14");
  const currency = url.searchParams.get("currency") ?? "USD";
  if (
    !Number.isInteger(history) ||
    history < 7 ||
    history > 90 ||
    !Number.isInteger(horizon) ||
    horizon < 1 ||
    horizon > 31 ||
    !/^[A-Z]{3}$/.test(currency)
  ) {
    ctx.problem(
      422,
      "invalid_request",
      undefined,
      "history_days 7-90, horizon_days 1-31, currency ISO 4217",
    );
    return true;
  }
  const available = currency !== "EUR";
  const body = {
    domain_id: domain,
    as_of: isoDay(0),
    method: {
      name: "linear_trend_ols",
      description: "Ordinary least squares trend over complete history days.",
      confidence_level: "0.95",
      z: "1.96",
      min_fit_points: 7,
      history_days: history,
      horizon_days: horizon,
      savings_claim: false,
    },
    price_version_id: "synthetic-prices-2026-10",
    price_version_ids: ["synthetic-prices-2026-10", "synthetic-prices-2026-09"],
    estimated: series("estimated", currency, history, horizon, available),
    invoiced: series("invoiced", currency, history, horizon, available),
  };
  ctx.res.writeHead(200, { "content-type": "application/json", ...ctx.cors });
  ctx.res.end(JSON.stringify(body));
  return true;
};
