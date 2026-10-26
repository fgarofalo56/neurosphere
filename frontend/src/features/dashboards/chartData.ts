import type { ChartSeries } from "../../design-system";
import { STRINGS } from "./strings";
import type { MetricValue, Series } from "./types";

/**
 * Pure mapping from the dashboards wire contract to chart input. Data-honesty rules live here so a
 * test can pin them: an unknown point is `null` (a gap in the chart, never 0), and series are
 * grouped by unit AND currency so one chart never mixes currencies or units, and nothing is summed.
 */

/** Chart value of one metric: the number when known, otherwise null (unknown). */
export function chartValue(m: MetricValue): number | null {
  return m.status === "known" && m.value !== null && Number.isFinite(m.value) ? m.value : null;
}

export function toChartSeries(series: Series): ChartSeries {
  return {
    key: series.key,
    label: series.label,
    kind: series.kind,
    unit: series.unit,
    currency: series.unit === "currency" ? series.currency : null,
    points: series.points.map((p) => ({
      t: p.t,
      value: chartValue(p.value),
      complete: p.value.complete,
    })),
  };
}

export interface ChartGroup {
  /** `unit` or `currency:<code>`; stable and unique per chart. */
  readonly key: string;
  readonly unit: Series["unit"];
  readonly currency: string | null;
  readonly series: readonly Series[];
}

/** One group per (unit, currency), in first-seen order. Estimated and invoiced of one currency share a group. */
export function groupSeries(series: readonly Series[]): ChartGroup[] {
  const groups = new Map<
    string,
    { unit: Series["unit"]; currency: string | null; items: Series[] }
  >();
  for (const s of series) {
    const currency = s.unit === "currency" ? s.currency : null;
    const key = s.unit === "currency" ? `currency:${currency ?? "none"}` : s.unit;
    const existing = groups.get(key);
    if (existing === undefined) {
      groups.set(key, { unit: s.unit, currency, items: [s] });
    } else {
      existing.items.push(s);
    }
  }
  return [...groups.entries()].map(([key, g]) => ({
    key,
    unit: g.unit,
    currency: g.currency,
    series: g.items,
  }));
}

const UNIT_TITLES = { ms: "Milliseconds", ratio: "Ratio", count: "Count" } as const;

export function groupTitle(group: ChartGroup, metric: string): string {
  if (group.unit === "currency") {
    const code = group.currency ?? STRINGS.undeterminedCurrency;
    return metric === "cost" ? `Cost in ${code}` : `Amounts in ${code}`;
  }
  return UNIT_TITLES[group.unit];
}
