export const MAX_DURATION_SECONDS = 7_776_000;

export interface Hm {
  readonly hours: number;
  readonly minutes: number;
  /** Seconds that do not fill a minute; kept so a value round-trips exactly. */
  readonly rest: number;
}

export function splitSeconds(total: number): Hm {
  const safe = Number.isFinite(total) && total > 0 ? Math.floor(total) : 0;
  return {
    hours: Math.floor(safe / 3600),
    minutes: Math.floor((safe % 3600) / 60),
    rest: safe % 60,
  };
}

export function joinSeconds(hm: Hm): number {
  return hm.hours * 3600 + hm.minutes * 60 + hm.rest;
}

/** "4 h 30 min" (plus "15 s" when there is a remainder). */
export function describeSeconds(total: number): string {
  const { hours, minutes, rest } = splitSeconds(total);
  const parts = [`${hours} h`, `${minutes} min`];
  if (rest > 0) parts.push(`${rest} s`);
  return parts.join(" ");
}

/** Whole non-negative number from an input, or undefined for anything else. */
export function wholeNumber(text: string): number | undefined {
  return /^[0-9]{1,7}$/.test(text.trim()) ? Number(text) : undefined;
}
