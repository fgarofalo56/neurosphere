import { useEffect, useState } from "react";
import type { ReactElement } from "react";
import { tokens } from "@fluentui/react-components";
import { ErrorState } from "../components";
import type { ChartSeriesTheme, ChartTheme } from "../styles";
import type { ChartPoint, ChartSeries, ChartUnit } from "./types";
import type { MixedSeriesError } from "./validate";

/* Small chart-local formatting helpers. Kept private to charts/ on purpose. */

const LOCALE = "en-US";

export function formatNumber(
  value: number,
  unit: ChartUnit,
  currency: string | null,
  compact = false,
): string {
  if (unit === "currency" && currency) {
    return new Intl.NumberFormat(LOCALE, {
      style: "currency",
      currency,
      notation: compact ? "compact" : "standard",
      maximumFractionDigits: compact ? 1 : 2,
    }).format(value);
  }
  if (unit === "ratio") {
    return new Intl.NumberFormat(LOCALE, { style: "percent", maximumFractionDigits: 1 }).format(
      value,
    );
  }
  const text = new Intl.NumberFormat(LOCALE, {
    notation: compact ? "compact" : "standard",
    maximumFractionDigits: compact ? 1 : 2,
  }).format(value);
  return unit === "ms" ? `${text} ms` : text;
}

export function formatSeriesValue(series: ChartSeries, value: number, compact = false): string {
  return formatNumber(value, series.unit, series.currency, compact);
}

const dayFormat = new Intl.DateTimeFormat(LOCALE, {
  timeZone: "UTC",
  month: "short",
  day: "numeric",
});
const dayLongFormat = new Intl.DateTimeFormat(LOCALE, {
  timeZone: "UTC",
  year: "numeric",
  month: "short",
  day: "numeric",
});
const hourFormat = new Intl.DateTimeFormat(LOCALE, {
  timeZone: "UTC",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});
const monthFormat = new Intl.DateTimeFormat(LOCALE, {
  timeZone: "UTC",
  month: "short",
  year: "numeric",
});

export type DateGrain = "hour" | "day" | "week" | "month";

/** Axis label. All dates are rendered in UTC so day-grain buckets never shift with the viewer. */
export function formatAxisDate(ms: number, grain: DateGrain): string {
  if (grain === "hour") return hourFormat.format(ms);
  if (grain === "month") return monthFormat.format(ms);
  return dayFormat.format(ms);
}

/** Tooltip and summary date: always the full UTC date (plus the time at hour grain). */
export function formatFullDate(ms: number, grain: DateGrain): string {
  return grain === "hour" ? `${hourFormat.format(ms)} UTC` : dayLongFormat.format(ms);
}

/** Legend text: the label alone for an unclassified (null-kind) series, else "label (basis)". */
export function legendLabel(series: ChartSeries): string {
  return series.kind === null ? series.label : `${series.label} (${series.kind})`;
}

export function basisWord(series: ChartSeries): string {
  return series.kind ?? "unclassified";
}

/** Stroke/fill style for one series. Several series of one basis fall back to the categorical palette. */
export function seriesStyle(
  series: ChartSeries,
  index: number,
  all: readonly ChartSeries[],
  chart: ChartTheme,
): ChartSeriesTheme {
  const categorical = chart.categorical[index % chart.categorical.length] ?? chart.invoiced.stroke;
  if (series.kind === null) {
    return { ...chart.invoiced, stroke: categorical, fill: categorical };
  }
  const base = series.kind === "estimated" ? chart.estimated : chart.invoiced;
  const shared = all.filter((s) => s.kind === series.kind).length > 1;
  return shared ? { ...base, stroke: categorical, fill: categorical } : base;
}

export interface Plotted {
  readonly ms: number;
  readonly value: number | null;
  readonly complete: boolean;
}

export function plotPoints(points: readonly ChartPoint[]): Plotted[] {
  return points
    .map((p) => ({
      ms: Date.parse(p.t),
      // NaN and Infinity are unknown, exactly like null (see knownValues).
      value: p.value !== null && Number.isFinite(p.value) ? p.value : null,
      complete: p.complete !== false,
    }))
    .filter((p) => Number.isFinite(p.ms))
    .sort((a, b) => a.ms - b.ms);
}

export function knownValues(series: readonly ChartSeries[]): number[] {
  return series.flatMap((s) =>
    s.points.flatMap((p) => (p.value !== null && Number.isFinite(p.value) ? [p.value] : [])),
  );
}

/** Generated accessible summary: series, range, min, max, latest and the unknown count. */
export function summarize(series: readonly ChartSeries[], grain: DateGrain): string {
  if (series.length === 0) return "Chart with no series";
  const parts = series.map((s) => {
    const pts = plotPoints(s.points);
    const known = pts.filter((p) => p.value !== null && Number.isFinite(p.value));
    const unknown = pts.length - known.length;
    const head = legendLabel(s);
    if (known.length === 0) return `${head}: no known values, ${unknown} unknown`;
    const values = known.map((p) => p.value as number);
    const last = known[known.length - 1] as Plotted;
    const first = pts[0] as Plotted;
    const end = pts[pts.length - 1] as Plotted;
    return (
      `${head}: ${formatFullDate(first.ms, grain)} to ${formatFullDate(end.ms, grain)}, ` +
      `min ${formatSeriesValue(s, Math.min(...values))}, max ${formatSeriesValue(s, Math.max(...values))}, ` +
      `latest ${formatSeriesValue(s, last.value as number)}, ${unknown} unknown`
    );
  });
  return `Chart. ${parts.join("; ")}`;
}

/** SVG path data: one "M x y L x y ..." sub-path per run of known points. Unknowns split runs. */
export function linePath(xy: readonly (readonly [number, number] | null)[]): string {
  const parts: string[] = [];
  let open = false;
  for (const p of xy) {
    if (p === null) {
      open = false;
      continue;
    }
    parts.push(`${open ? "L" : "M"}${round(p[0])} ${round(p[1])}`);
    open = true;
  }
  return parts.join(" ");
}

/** Closed area sub-paths down to the baseline, one per run of known points. */
export function areaPath(
  xy: readonly (readonly [number, number] | null)[],
  baseline: number,
): string {
  const runs: (readonly [number, number])[][] = [];
  let current: (readonly [number, number])[] | null = null;
  for (const p of xy) {
    if (p === null) {
      current = null;
      continue;
    }
    if (current === null) {
      current = [];
      runs.push(current);
    }
    current.push(p);
  }
  return runs
    .filter((run) => run.length > 1)
    .map((run) => {
      const first = run[0] as readonly [number, number];
      const last = run[run.length - 1] as readonly [number, number];
      const top = run
        .map((p, i) => `${i === 0 ? "M" : "L"}${round(p[0])} ${round(p[1])}`)
        .join(" ");
      return `${top} L${round(last[0])} ${round(baseline)} L${round(first[0])} ${round(baseline)} Z`;
    })
    .join(" ");
}

function round(n: number): number {
  return Math.round(n * 100) / 100;
}

/** True only when the user has no reduced-motion preference. matchMedia is absent in jsdom. */
export function useMotionAllowed(): boolean {
  const read = (): boolean =>
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: no-preference)").matches;
  const [allowed, setAllowed] = useState<boolean>(read);
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return undefined;
    const query = window.matchMedia("(prefers-reduced-motion: no-preference)");
    const onChange = (): void => setAllowed(query.matches);
    onChange();
    query.addEventListener?.("change", onChange);
    return () => query.removeEventListener?.("change", onChange);
  }, []);
  return allowed;
}

/** Accessible error presentation for invalid chart input (the design-system ErrorState). */
export function ChartError({ error }: { error: MixedSeriesError }): ReactElement {
  return (
    <ErrorState
      title="Chart cannot be drawn"
      message={`${error.message}. Split the series into one chart per unit and currency.`}
    />
  );
}

export interface TooltipRow {
  readonly key: string;
  readonly label: string;
  readonly basis: string;
  readonly value: string;
  readonly complete: boolean;
}

/** HTML tooltip overlay. Positioned in percentages of the chart box so it scales with the SVG. */
export function ChartTooltip({
  chart,
  date,
  rows,
  leftPct,
  motion,
}: {
  chart: ChartTheme;
  date: string;
  rows: readonly TooltipRow[];
  leftPct: number;
  motion: boolean;
}): ReactElement {
  const flip = leftPct > 60;
  return (
    <div
      role="tooltip"
      data-testid="chart-tooltip"
      style={{
        position: "absolute",
        top: 0,
        left: `${leftPct}%`,
        transform: flip ? "translateX(calc(-100% - 8px))" : "translateX(8px)",
        pointerEvents: "none",
        background: chart.tooltip.background,
        color: chart.tooltip.foreground,
        border: `1px solid ${chart.tooltip.border}`,
        borderRadius: tokens.borderRadiusMedium,
        padding: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalS}`,
        fontSize: tokens.fontSizeBase200,
        transition: motion ? "left 120ms ease-out" : undefined,
        zIndex: 1,
      }}
    >
      <div style={{ fontWeight: tokens.fontWeightSemibold }}>{date}</div>
      {rows.map((row) => (
        <div key={row.key}>
          {row.basis === "unclassified" ? row.label : `${row.label} (${row.basis})`}: {row.value}
          {row.complete ? "" : " (incomplete)"}
        </div>
      ))}
    </div>
  );
}
