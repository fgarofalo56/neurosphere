import { describe, expect, it } from "vitest";
import { linearScale, niceTicks, timeTicks } from "./scale";

const utc = (y: number, m: number, d: number, h = 0): number => Date.UTC(y, m - 1, d, h);

describe("niceTicks", () => {
  it("returns a default axis for empty or non-finite input", () => {
    expect(niceTicks(Number.NaN, 1)).toEqual([0, 0.5, 1]);
    expect(niceTicks(Infinity, Infinity)).toEqual([0, 0.5, 1]);
    expect(niceTicks(5, 1)).toEqual([0, 0.5, 1]);
  });

  it("pads a single value so the axis still spans it", () => {
    const ticks = niceTicks(5, 5);
    expect(ticks.length).toBeGreaterThan(1);
    expect(ticks[0]).toBeLessThan(5);
    expect(ticks[ticks.length - 1]).toBeGreaterThan(5);
    expect(niceTicks(0, 0)[0]).toBeLessThan(0);
  });

  it("covers the range with round steps", () => {
    expect(niceTicks(0, 97)).toEqual([0, 50, 100]);
    const t = niceTicks(0, 1);
    expect(t[0]).toBe(0);
    expect(t[t.length - 1]).toBe(1);
  });

  it("handles negative ranges", () => {
    const t = niceTicks(-37, 12);
    expect(t[0]).toBeLessThanOrEqual(-37);
    expect(t[t.length - 1]).toBeGreaterThanOrEqual(12);
    expect(t).toContain(0);
  });

  it("handles large values without float noise", () => {
    const t = niceTicks(0, 3_400_000_000);
    expect(t[t.length - 1]).toBeGreaterThanOrEqual(3_400_000_000);
    for (const v of t) expect(Number.isInteger(v)).toBe(true);
  });

  it("has no float noise for fractions", () => {
    expect(niceTicks(0, 0.3, 4).every((v) => String(v).length < 8)).toBe(true);
  });
});

describe("linearScale", () => {
  it("maps domain to range", () => {
    const s = linearScale(0, 10, 100, 0);
    expect(s(0)).toBe(100);
    expect(s(10)).toBe(0);
    expect(s(5)).toBe(50);
  });
  it("maps a zero-width domain to the midpoint", () => {
    expect(linearScale(3, 3, 0, 100)(3)).toBe(50);
  });
});

describe("timeTicks", () => {
  it("is empty for invalid input and a single tick for a single point", () => {
    expect(timeTicks(Number.NaN, 1, "day")).toEqual([]);
    expect(timeTicks(10, 5, "day")).toEqual([]);
    expect(timeTicks(utc(2026, 3, 4), utc(2026, 3, 4), "day")).toEqual([utc(2026, 3, 4)]);
  });

  it("aligns day ticks to UTC midnight", () => {
    const ticks = timeTicks(utc(2026, 3, 1), utc(2026, 3, 5), "day", 10);
    expect(ticks).toEqual([1, 2, 3, 4, 5].map((d) => utc(2026, 3, d)));
  });

  it("thins day ticks to the max", () => {
    const ticks = timeTicks(utc(2026, 1, 1), utc(2026, 3, 31), "day", 6);
    expect(ticks.length).toBeLessThanOrEqual(6);
    for (const t of ticks) expect(t % 86_400_000).toBe(0);
  });

  it("aligns hour ticks on the hour", () => {
    const ticks = timeTicks(utc(2026, 3, 1, 0) + 1800_000, utc(2026, 3, 1, 5), "hour", 10);
    expect(ticks).toEqual([1, 2, 3, 4, 5].map((h) => utc(2026, 3, 1, h)));
  });

  it("aligns week ticks to Monday", () => {
    const ticks = timeTicks(utc(2026, 3, 1), utc(2026, 4, 1), "week", 10);
    expect(ticks.length).toBeGreaterThan(2);
    for (const t of ticks) expect(new Date(t).getUTCDay()).toBe(1);
  });

  it("aligns month ticks to the 1st", () => {
    const ticks = timeTicks(utc(2025, 11, 15), utc(2026, 3, 20), "month", 10);
    expect(ticks).toEqual([utc(2025, 12, 1), utc(2026, 1, 1), utc(2026, 2, 1), utc(2026, 3, 1)]);
  });

  it("falls back to the endpoints when no aligned tick fits", () => {
    const a = utc(2026, 3, 1, 1) + 600_000;
    const b = a + 1_200_000;
    expect(timeTicks(a, b, "hour")).toEqual([a, b]);
  });
});
