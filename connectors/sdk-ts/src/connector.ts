// BaseConnector: the class every NeuroSphere TypeScript connector extends.
//
// A subclass supplies a contract-valid `manifest` and does its work inside guardedCall so
// success, rate limiting and failures feed health(). Credentials are fetched per call through
// credential() (never stored on the instance), which is what makes rotation take effect without
// a restart. Read-side only: there is no write surface.

import type { ConnectorManifest } from "@neurosphere/contracts";

import {
  type Clock,
  type CoverageReport,
  type FreshnessReport,
  type HealthReport,
  HealthTracker,
  utcNow,
} from "./health.js";
import type { CredentialBroker, SecretValue } from "./vault.js";

export interface BaseConnectorOptions {
  credentials?: CredentialBroker;
  clock?: Clock;
}

export interface GuardedCallOptions<T> {
  freshness?: (result: T) => FreshnessReport | null;
  coverage?: (result: T) => CoverageReport | null;
}

export abstract class BaseConnector {
  readonly #credentials: CredentialBroker | undefined;
  readonly #tracker: HealthTracker;
  closed = false;

  protected constructor(options: BaseConnectorOptions = {}) {
    this.#credentials = options.credentials;
    this.#tracker = new HealthTracker({ clock: options.clock ?? utcNow });
  }

  /** The connector's registration manifest (use buildManifest). */
  abstract get manifest(): ConnectorManifest;

  /** Current health, including rate-limit status, coverage and freshness. */
  health(): Promise<HealthReport> {
    return Promise.resolve(this.#tracker.snapshot());
  }

  /** Fraction of expected sources that answered on the last successful call. */
  async coverage(): Promise<CoverageReport> {
    return (await this.health()).coverage;
  }

  /** Data lag on the last successful call; lagMs is null when unknown. */
  async freshness(): Promise<FreshnessReport> {
    return (await this.health()).freshness;
  }

  /** Resolve a declared credential now (always via the broker, so rotation applies). */
  credential(name: string): Promise<SecretValue> {
    if (this.#credentials === undefined) {
      return Promise.reject(new Error("connector was created without a credential broker"));
    }
    return this.#credentials.get(name);
  }

  /** Run `operation`, recording the outcome in health; errors are re-thrown unchanged. */
  async guardedCall<T>(
    operation: () => Promise<T>,
    options: GuardedCallOptions<T> = {},
  ): Promise<T> {
    let result: T;
    try {
      result = await operation();
    } catch (error) {
      this.#tracker.recordError(error);
      throw error;
    }
    this.#tracker.recordSuccess({
      freshness: options.freshness?.(result) ?? null,
      coverage: options.coverage?.(result) ?? null,
    });
    return result;
  }

  /** Release resources; subclasses extend and call `await super.close()`. */
  close(): Promise<void> {
    this.closed = true;
    return Promise.resolve();
  }
}
