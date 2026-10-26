/**
 * Display formatters. Data-honesty rules: null, undefined and non-finite input is "unknown",
 * never 0; currency is formatted one currency per call and never summed or converted.
 * All formatters use the en-US locale and UTC for dates so output is deterministic.
 */

export const UNKNOWN_TEXT = "unknown";

export type TimeInput = string | number | Date | null | undefined;

function toDate(value: TimeInput): Date | null {
  if (value === null || value === undefined) return null;
  const d = value instanceof Date ? value : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** Plain number with grouping; "unknown" for null/undefined/NaN. A real 0 renders "0". */
export function formatNumber(
  value: number | null | undefined,
  options: { readonly maximumFractionDigits?: number; readonly compact?: boolean } = {},
): string {
  if (!isFiniteNumber(value)) return UNKNOWN_TEXT;
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: options.maximumFractionDigits ?? 2,
    ...(options.compact === true ? { notation: "compact" as const } : {}),
  }).format(value);
}

/**
 * Amount in exactly one ISO 4217 currency. The signature takes a single code so a caller cannot
 * hand it a mixed-currency total; there is no summing or conversion here.
 */
export function formatCurrency(
  value: number | null | undefined,
  currency: string,
  options: { readonly maximumFractionDigits?: number } = {},
): string {
  if (!isFiniteNumber(value)) return UNKNOWN_TEXT;
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      ...(options.maximumFractionDigits === undefined
        ? {}
        : { maximumFractionDigits: options.maximumFractionDigits }),
    }).format(value);
  } catch {
    // Unrecognised currency code: show the number with the code, never drop the currency.
    return `${formatNumber(value)} ${currency}`;
  }
}

/** Milliseconds as a short duration such as "1h 2m 3s" or "250 ms". */
export function formatDuration(ms: number | null | undefined): string {
  if (!isFiniteNumber(ms) || ms < 0) return UNKNOWN_TEXT;
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const totalSeconds = Math.floor(ms / 1000);
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const parts: string[] = [];
  if (days > 0) parts.push(`${days}d`);
  if (hours > 0) parts.push(`${hours}h`);
  if (minutes > 0) parts.push(`${minutes}m`);
  if (seconds > 0 || parts.length === 0) parts.push(`${seconds}s`);
  return parts.join(" ");
}

const RELATIVE_UNITS: readonly (readonly [Intl.RelativeTimeFormatUnit, number])[] = [
  ["year", 31_536_000],
  ["month", 2_592_000],
  ["day", 86_400],
  ["hour", 3600],
  ["minute", 60],
  ["second", 1],
];

/** "3 hours ago" / "in 2 days" relative to `now`; "unknown" for missing or invalid input. */
export function formatRelativeTime(value: TimeInput, now: TimeInput = new Date()): string {
  const d = toDate(value);
  const ref = toDate(now);
  if (d === null || ref === null) return UNKNOWN_TEXT;
  const diffSeconds = Math.round((d.getTime() - ref.getTime()) / 1000);
  const rtf = new Intl.RelativeTimeFormat("en-US", { numeric: "auto" });
  for (const [unit, size] of RELATIVE_UNITS) {
    if (Math.abs(diffSeconds) >= size || unit === "second") {
      return rtf.format(Math.trunc(diffSeconds / size), unit);
    }
  }
  return UNKNOWN_TEXT;
}

/** Absolute instant in UTC, e.g. "2026-03-04 05:06 UTC". */
export function formatAbsoluteTime(value: TimeInput): string {
  const d = toDate(value);
  if (d === null) return UNKNOWN_TEXT;
  return `${d.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

/** Calendar day in UTC, e.g. "2026-03-04". Never shifts by the viewer's time zone. */
export function formatUtcDay(value: TimeInput): string {
  const d = toDate(value);
  if (d === null) return UNKNOWN_TEXT;
  return d.toISOString().slice(0, 10);
}
