import type { ChartSeries } from "./types";

/** Thrown when series that do not share one unit and one currency are drawn on one axis. */
export class MixedSeriesError extends Error {
  readonly units: readonly string[];
  readonly currencies: readonly string[];

  constructor(units: readonly string[], currencies: readonly string[]) {
    const parts: string[] = [];
    if (units.length > 1) parts.push(`units (${units.join(", ")})`);
    if (currencies.length > 1) parts.push(`currencies (${currencies.join(", ")})`);
    super(`Cannot plot mixed ${parts.join(" and ")} on one axis`);
    this.name = "MixedSeriesError";
    this.units = units;
    this.currencies = currencies;
  }
}

/** Pure check: all series share ONE unit and ONE currency. Throws MixedSeriesError otherwise. */
export function assertSingleUnitAndCurrency(series: readonly ChartSeries[]): void {
  const units = [...new Set(series.map((s) => s.unit))];
  const currencies = [
    ...new Set(series.filter((s) => s.unit === "currency").map((s) => s.currency ?? "none")),
  ];
  if (units.length > 1 || currencies.length > 1) throw new MixedSeriesError(units, currencies);
}

/** Non-throwing wrapper for components: the error, or null when the series are consistent. */
export function checkSeries(series: readonly ChartSeries[]): MixedSeriesError | null {
  try {
    assertSingleUnitAndCurrency(series);
    return null;
  } catch (error) {
    if (error instanceof MixedSeriesError) return error;
    throw error;
  }
}
