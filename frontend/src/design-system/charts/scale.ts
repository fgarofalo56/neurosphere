/** Pure scale and tick math for the chart primitives. No DOM, no dependencies. */

export type TimeGrain = "hour" | "day" | "week" | "month";

const HOUR = 3_600_000;
const DAY = 24 * HOUR;
const WEEK = 7 * DAY;
/** 1970-01-01 was a Thursday; Monday-aligned weeks start 4 days after the epoch. */
const MONDAY_OFFSET = 4 * DAY;

function cleanNumber(value: number): number {
  return Number(value.toPrecision(12));
}

function niceStep(rough: number): number {
  const exponent = Math.floor(Math.log10(rough));
  const base = 10 ** exponent;
  const fraction = rough / base;
  const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
  return nice * base;
}

/**
 * Nice numeric ticks covering [min, max]. Non-finite or inverted input falls back to [0, 1];
 * a degenerate range (min === max) is padded so a single value still gets an axis.
 */
export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min > max) return [0, 0.5, 1];
  let lo = min;
  let hi = max;
  if (lo === hi) {
    const pad = Math.abs(lo) * 0.1 || 1;
    lo -= pad;
    hi += pad;
  }
  const slots = Math.max(1, count - 1);
  const step = niceStep((hi - lo) / slots);
  const start = Math.floor(lo / step) * step;
  const end = Math.ceil(hi / step) * step;
  const ticks: number[] = [];
  const n = Math.round((end - start) / step);
  for (let i = 0; i <= n; i += 1) ticks.push(cleanNumber(start + i * step));
  return ticks;
}

/** Linear map from a domain to a range. A zero-width domain maps to the range midpoint. */
export function linearScale(
  d0: number,
  d1: number,
  r0: number,
  r1: number,
): (value: number) => number {
  if (d0 === d1) return () => (r0 + r1) / 2;
  const k = (r1 - r0) / (d1 - d0);
  return (value) => r0 + (value - d0) * k;
}

function alignedTicks(
  min: number,
  max: number,
  unit: number,
  step: number,
  offset: number,
): number[] {
  const size = unit * step;
  const first = Math.ceil((min - offset) / size) * size + offset;
  const out: number[] = [];
  for (let t = first; t <= max; t += size) out.push(t);
  return out;
}

function monthTicks(min: number, max: number, step: number): number[] {
  const start = new Date(min);
  let year = start.getUTCFullYear();
  let month = Math.ceil(start.getUTCMonth() / step) * step;
  const out: number[] = [];
  for (let guard = 0; guard < 1000; guard += 1) {
    const t = Date.UTC(year, month, 1);
    if (t > max) break;
    if (t >= min) out.push(t);
    month += step;
    if (month >= 12) {
      year += Math.floor(month / 12);
      month %= 12;
    }
  }
  return out;
}

const STEPS: Record<TimeGrain, readonly number[]> = {
  hour: [1, 2, 3, 6, 12, 24, 48],
  day: [1, 2, 5, 10, 15, 30, 60, 90],
  week: [1, 2, 4, 8, 13, 26, 52],
  month: [1, 2, 3, 6, 12, 24, 60],
};

/**
 * UTC-aligned time ticks (epoch ms) for a grain: hour on the hour, day at UTC midnight, week on
 * Monday, month on the 1st. The step grows until at most `maxTicks` ticks fall in [min, max].
 */
export function timeTicks(minMs: number, maxMs: number, grain: TimeGrain, maxTicks = 6): number[] {
  if (!Number.isFinite(minMs) || !Number.isFinite(maxMs) || minMs > maxMs) return [];
  if (minMs === maxMs) return [minMs];
  let last: number[] = [];
  for (const step of STEPS[grain]) {
    const ticks =
      grain === "month"
        ? monthTicks(minMs, maxMs, step)
        : alignedTicks(
            minMs,
            maxMs,
            grain === "hour" ? HOUR : grain === "day" ? DAY : WEEK,
            step,
            grain === "week" ? MONDAY_OFFSET : 0,
          );
    last = ticks;
    if (ticks.length <= maxTicks) break;
  }
  if (last.length === 0) return [minMs, maxMs];
  return last.slice(0, maxTicks);
}
