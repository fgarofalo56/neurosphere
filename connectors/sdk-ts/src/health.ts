// Connector health, rate-limit, coverage and freshness reporting and tracker.
//
// Unknown is null, never zero. Errors map to states by ConnectorError.code only; error message
// text is never copied into a report (it could hold provider response bodies).

import { ConnectorError, RateLimitedError } from "./errors.js";

export type Clock = () => Date;

export const utcNow: Clock = () => new Date();

export type HealthState = "healthy" | "degraded" | "rate_limited" | "failing" | "unknown";

/** Observed data lag. lagMs is null when unknown (never 0). */
export interface FreshnessReport {
  readonly lagMs: number | null;
  readonly watermark: Date | null;
  readonly observedAt: Date | null;
}

/** What fraction of expected sources answered. Unknown counts are null. */
export interface CoverageReport {
  readonly expectedSources: number | null;
  readonly answeredSources: number | null;
  readonly partial: boolean | null;
}

export interface RateLimitStatus {
  readonly limited: boolean;
  readonly retryAfterSeconds: number | null;
  readonly limitedUntil: Date | null;
  readonly remaining: number | null;
}

export interface HealthReport {
  readonly state: HealthState;
  readonly checkedAt: Date;
  readonly rateLimit: RateLimitStatus;
  readonly freshness: FreshnessReport;
  readonly coverage: CoverageReport;
  readonly consecutiveFailures: number;
  readonly lastErrorCode: string | null;
}

export const unknownFreshness = (): FreshnessReport => ({
  lagMs: null,
  watermark: null,
  observedAt: null,
});

export const unknownCoverage = (): CoverageReport => ({
  expectedSources: null,
  answeredSources: null,
  partial: null,
});

/** answered / expected; null when unknown or nothing was expected. */
export function coverageFraction(report: CoverageReport): number | null {
  if (!report.expectedSources || report.answeredSources === null) {
    return null;
  }
  return report.answeredSources / report.expectedSources;
}

/** Validating constructor: answered may not exceed expected. */
export function makeCoverage(init: Partial<CoverageReport>): CoverageReport {
  const report = { ...unknownCoverage(), ...init };
  if (
    report.expectedSources !== null &&
    report.answeredSources !== null &&
    report.answeredSources > report.expectedSources
  ) {
    throw new RangeError("answeredSources exceeds expectedSources");
  }
  return report;
}

// Non-retryable codes (and unclassified errors) will not heal by waiting.
const HARD_FAILURES: ReadonlySet<string> = new Set([
  "unauthorized",
  "forbidden",
  "invalid_schema",
  "capability_unavailable",
  "internal_error",
]);

export interface HealthTrackerOptions {
  clock?: Clock;
  failingAfter?: number;
}

/** Accumulates call outcomes and renders a HealthReport. */
export class HealthTracker {
  readonly #clock: Clock;
  readonly #failingAfter: number;
  #seen = false;
  #failures = 0;
  #lastCode: string | null = null;
  #rateLimited = false;
  #limitedUntil: Date | null = null;
  #retryAfter: number | null = null;
  #remaining: number | null = null;
  #freshness: FreshnessReport = unknownFreshness();
  #coverage: CoverageReport = unknownCoverage();

  constructor(options: HealthTrackerOptions = {}) {
    this.#clock = options.clock ?? utcNow;
    this.#failingAfter = options.failingAfter ?? 3;
  }

  recordSuccess(
    outcome: {
      freshness?: FreshnessReport | null;
      coverage?: CoverageReport | null;
      remaining?: number | null;
    } = {},
  ): void {
    this.#seen = true;
    this.#failures = 0;
    this.#lastCode = null;
    this.#rateLimited = false;
    this.#limitedUntil = null;
    this.#retryAfter = null;
    this.#remaining = outcome.remaining ?? null;
    if (outcome.freshness) this.#freshness = outcome.freshness;
    if (outcome.coverage) this.#coverage = outcome.coverage;
  }

  recordError(error: unknown): void {
    this.#seen = true;
    this.#failures += 1;
    this.#rateLimited = false;
    if (!(error instanceof ConnectorError)) {
      this.#lastCode = "internal_error";
      return;
    }
    this.#lastCode = error.code;
    if (error instanceof RateLimitedError) {
      this.#rateLimited = true;
      this.#remaining = 0;
      this.#retryAfter = error.retryAfterSeconds;
      if (error.retryAfterSeconds !== null) {
        this.#limitedUntil = new Date(this.#clock().getTime() + error.retryAfterSeconds * 1000);
      }
    }
  }

  snapshot(): HealthReport {
    const now = this.#clock();
    const limited =
      this.#rateLimited && (this.#limitedUntil === null || now.getTime() < this.#limitedUntil.getTime());
    let state: HealthState;
    if (!this.#seen) state = "unknown";
    else if (limited) state = "rate_limited";
    else if (this.#failures === 0) state = "healthy";
    else if (
      this.#failures >= this.#failingAfter ||
      (this.#lastCode !== null && HARD_FAILURES.has(this.#lastCode))
    )
      state = "failing";
    else state = "degraded";
    return {
      state,
      checkedAt: now,
      rateLimit: {
        limited,
        retryAfterSeconds: limited ? this.#retryAfter : null,
        limitedUntil: limited ? this.#limitedUntil : null,
        remaining: this.#remaining,
      },
      freshness: this.#freshness,
      coverage: this.#coverage,
      consecutiveFailures: this.#failures,
      lastErrorCode: this.#lastCode,
    };
  }
}
