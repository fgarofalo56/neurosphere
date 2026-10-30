import { createQueryHook } from "../../api/index.js";
import { forecastPath } from "./paths";

/**
 * Response shapes of `GET /api/v1/finops/domains/{d}/forecast` (services/api finops/models.py).
 * Money arrives as a decimal STRING; it is parsed for display and plotting only, never summed here.
 */
export interface Amount {
  readonly value: string | null;
  readonly status: "known" | "unknown";
  readonly complete: boolean;
  readonly reason?: string | null;
}

export interface ForecastValue {
  readonly value: string;
  readonly lower: string;
  readonly upper: string;
}

export interface SeriesPoint {
  readonly day: string;
  readonly phase: "history" | "horizon";
  readonly actual: Amount;
  readonly forecast?: ForecastValue | null;
  readonly within_band?: boolean | null;
}

export interface SeriesSummary {
  readonly history_actual: Amount;
  readonly horizon_actual: Amount;
  readonly horizon_forecast?: ForecastValue | null;
}

export interface CostSeries {
  readonly kind: "estimated" | "invoiced";
  readonly currency: string;
  readonly points: readonly SeriesPoint[];
  readonly summary: SeriesSummary;
  readonly forecast_available: boolean;
  readonly forecast_unavailable_reason?: string | null;
  readonly fit_points: number;
  readonly excluded_incomplete_days: number;
  readonly residual_std?: string | null;
}

export interface ForecastMethod {
  readonly name: string;
  readonly description: string;
  readonly confidence_level: string;
  readonly z: string;
  readonly min_fit_points: number;
  readonly history_days: number;
  readonly horizon_days: number;
  readonly savings_claim?: boolean;
}

export interface ForecastResponse {
  readonly domain_id: string;
  readonly as_of: string;
  readonly method: ForecastMethod;
  readonly price_version_id: string;
  readonly price_version_ids: readonly string[];
  readonly estimated: CostSeries;
  readonly invoiced: CostSeries;
}

export interface ForecastParams {
  readonly domainId: string;
  readonly historyDays: number;
  readonly horizonDays: number;
  readonly currency: string;
}

export const useForecast = createQueryHook<ForecastParams, ForecastResponse>({
  key: "finops-forecast",
  fetcher: (client, p, signal) =>
    client.get<ForecastResponse>(
      forecastPath(p.domainId),
      { history_days: p.historyDays, horizon_days: p.horizonDays, currency: p.currency },
      signal,
    ),
});

/** Clamp an untrusted URL value to one of the allowed options, else the default. */
export function pickOption<T extends number>(
  raw: string | null,
  options: readonly T[],
  fallback: T,
): T {
  const n = Number(raw);
  return options.find((o) => o === n) ?? fallback;
}

/** Display number for a decimal string; null when absent or not finite (never 0). */
export function toNumber(value: string | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}
