/**
 * Money handling without floats. Amounts travel as decimal strings (`DecimalAmount`: up to 18
 * integer digits, up to 12 fraction digits). Nothing here calls `Number()` or `parseFloat()` on an
 * amount, so `0.1` stays `0.1` and a long fraction is never rounded.
 */
export const DECIMAL_AMOUNT = /^(0|[1-9][0-9]{0,17})(\.[0-9]{1,12})?$/;

export function isDecimalAmount(value: string): boolean {
  return DECIMAL_AMOUNT.test(value);
}

/** Shows a decimal string as received; a missing price is "Unknown", never 0. */
export function showAmount(value: string | null | undefined): string {
  return value === null || value === undefined || value === "" ? "Unknown" : value;
}

/** Parses "50, 80,100" into whole-number percents 1..1000, or undefined when any is wrong. */
export function parseThresholds(text: string): number[] | undefined {
  const parts = text
    .split(",")
    .map((p) => p.trim())
    .filter((p) => p !== "");
  if (parts.length === 0 || parts.length > 10) return undefined;
  const out: number[] = [];
  for (const part of parts) {
    if (!/^[0-9]{1,4}$/.test(part)) return undefined;
    const n = Number(part);
    if (n < 1 || n > 1000) return undefined;
    out.push(n);
  }
  return out;
}
