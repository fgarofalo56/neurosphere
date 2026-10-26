import { describe, expect, it, vi } from "vitest";
import {
  formatAbsoluteTime,
  formatCurrency,
  formatDuration,
  formatNumber,
  formatRelativeTime,
  formatUtcDay,
} from "./index";

describe("format helpers never turn missing data into 0", () => {
  it("returns unknown for null, undefined and non-finite numbers", () => {
    for (const v of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(formatNumber(v)).toBe("unknown");
      expect(formatCurrency(v, "USD")).toBe("unknown");
      expect(formatDuration(v)).toBe("unknown");
    }
    expect(formatRelativeTime(null)).toBe("unknown");
    expect(formatAbsoluteTime(undefined)).toBe("unknown");
    expect(formatUtcDay("not a date")).toBe("unknown");
  });

  it("renders a real zero as 0", () => {
    expect(formatNumber(0)).toBe("0");
    expect(formatCurrency(0, "USD")).toBe("$0.00");
    expect(formatDuration(0)).toBe("0 ms");
  });
});

describe("formatters", () => {
  it("formats numbers and compact numbers", () => {
    expect(formatNumber(1234567.891)).toBe("1,234,567.89");
    expect(formatNumber(1500, { compact: true })).toBe("1.5K");
  });

  it("formats one currency per call and keeps the currency visible", () => {
    expect(formatCurrency(12.5, "USD")).toBe("$12.50");
    expect(formatCurrency(12.5, "EUR")).toBe("€12.50");
    expect(formatCurrency(1, "not-a-code")).toContain("not-a-code");
  });

  it("formats durations", () => {
    expect(formatDuration(250)).toBe("250 ms");
    expect(formatDuration(3_723_000)).toBe("1h 2m 3s");
    expect(formatDuration(90_000_000)).toBe("1d 1h");
    expect(formatDuration(-5)).toBe("unknown");
  });

  it("formats relative and absolute time deterministically", () => {
    const now = "2026-03-04T12:00:00Z";
    expect(formatRelativeTime("2026-03-04T09:00:00Z", now)).toBe("3 hours ago");
    expect(formatRelativeTime("2026-03-06T12:00:00Z", now)).toBe("in 2 days");
    expect(formatAbsoluteTime("2026-03-04T05:06:59Z")).toBe("2026-03-04 05:06 UTC");
  });

  it("formats UTC days without shifting by time zone", () => {
    vi.stubEnv("TZ", "America/Los_Angeles");
    try {
      expect(formatUtcDay("2026-03-04T00:00:00Z")).toBe("2026-03-04");
      expect(formatUtcDay(new Date(Date.UTC(2026, 0, 1)))).toBe("2026-01-01");
    } finally {
      vi.unstubAllEnvs();
    }
  });
});
