// Vault credential references, an injected async resolver and a rotation hook (PRP-09 cl. 5).
//
// Manifests carry CredentialRef values only. At call time a CredentialBroker asks the injected
// CredentialResolver for the value and hands back a SecretValue, a wrapper whose toString,
// toJSON, template/format use and util.inspect never expose the secret. Only reveal() returns it,
// at the point of use. On rotation call notifyRotated (or let a RotationSource resolver do so):
// the cache entry is dropped, hooks run, and the next get resolves the new value.
// Errors and log fields carry the logical credential name only, never a value.

import type { ConnectorManifest } from "@neurosphere/contracts";

import { CapabilityUnavailableError, DependencyTransientError } from "./errors.js";

export type CredentialRef = ConnectorManifest["credential_refs"][number];

const MASK = "***";

/** A secret string that cannot leak through toString, JSON, template strings or inspect. */
export class SecretValue {
  readonly #value: string;

  constructor(value: string) {
    this.#value = value;
    Object.freeze(this);
  }

  /** Return the secret. Call only where it is handed to the provider client. */
  reveal(): string {
    return this.#value;
  }

  /** Constant-time-ish comparison without revealing either value. */
  equals(other: unknown): boolean {
    if (!(other instanceof SecretValue)) return false;
    const a = this.#value;
    const b = other.#value;
    let diff = a.length ^ b.length;
    for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
      diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
    }
    return diff === 0;
  }

  toString(): string {
    return `SecretValue(${MASK})`;
  }

  toJSON(): string {
    return MASK;
  }

  [Symbol.toPrimitive](): string {
    return this.toString();
  }

  [Symbol.for("nodejs.util.inspect.custom")](): string {
    return this.toString();
  }
}

/** Injected by the host; resolves a vault reference (managed identity) to its value. */
export interface CredentialResolver {
  resolve(ref: CredentialRef): Promise<SecretValue>;
}

/** Receives the logical credential name (never a value); may be sync or async. */
export type RotationCallback = (name: string) => void | Promise<void>;

/** Optional resolver capability: pushes rotation signals to the broker. */
export interface RotationSource {
  subscribe(callback: (name: string) => void): void;
}

function isRotationSource(value: unknown): value is RotationSource {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { subscribe?: unknown }).subscribe === "function"
  );
}

/** Minimal logger seam; fields hold the credential name only. */
export interface CredentialLogger {
  warn(message: string, fields: { credential: string }): void;
  info(message: string, fields: { credential: string }): void;
}

/** In-memory resolver for tests and local sandboxes; values keyed by vault_ref. */
export class StaticCredentialResolver implements CredentialResolver, RotationSource {
  readonly #values: Map<string, string>;
  readonly #subscribers: ((name: string) => void)[] = [];

  constructor(values: Readonly<Record<string, string>>) {
    this.#values = new Map(Object.entries(values));
  }

  resolve(ref: CredentialRef): Promise<SecretValue> {
    const value = this.#values.get(ref.vault_ref);
    if (value === undefined) {
      return Promise.reject(new Error("no such secret"));
    }
    return Promise.resolve(new SecretValue(value));
  }

  subscribe(callback: (name: string) => void): void {
    this.#subscribers.push(callback);
  }

  /** Replace a value and signal subscribers (what a Key Vault event bridge would do). */
  rotate(ref: CredentialRef, newValue: string): void {
    this.#values.set(ref.vault_ref, newValue);
    for (const callback of this.#subscribers) callback(ref.name);
  }
}

/** Resolves the connector's declared credential refs at call time, with rotation. */
export class CredentialBroker {
  readonly #resolver: CredentialResolver;
  readonly #refs: Map<string, CredentialRef>;
  readonly #cache = new Map<string, SecretValue>();
  readonly #hooks: RotationCallback[] = [];
  readonly #logger: CredentialLogger | undefined;
  #pending: Promise<void>[] = [];

  constructor(
    resolver: CredentialResolver,
    refs: Iterable<CredentialRef> = [],
    logger?: CredentialLogger,
  ) {
    this.#resolver = resolver;
    this.#refs = new Map([...refs].map((r) => [r.name, r]));
    this.#logger = logger;
    if (isRotationSource(resolver)) {
      resolver.subscribe((name) => this.#onSourceSignal(name));
    }
  }

  get names(): readonly string[] {
    return [...this.#refs.keys()];
  }

  /** Register a hook invoked with the credential name after a rotation signal. */
  onRotation(callback: RotationCallback): void {
    this.#hooks.push(callback);
  }

  /** Current value for a declared credential (cached until rotated). */
  async get(name: string): Promise<SecretValue> {
    const cached = this.#cache.get(name);
    if (cached !== undefined) return cached;
    const ref = this.#refs.get(name);
    if (ref === undefined) {
      throw new CapabilityUnavailableError("credential_not_declared", `credential '${name}'`);
    }
    let value: SecretValue;
    try {
      value = await this.#resolver.resolve(ref);
    } catch {
      // Never chain or echo the resolver's text: it may hold provider response bodies.
      this.#logger?.warn("credential resolution failed", { credential: name });
      throw new DependencyTransientError(
        `credential '${name}' could not be resolved`,
        "credential_resolution_failed",
      );
    }
    this.#cache.set(name, value);
    return value;
  }

  /** Drop cached value(s) and run hooks; the next get resolves the new value. */
  async notifyRotated(name?: string): Promise<void> {
    const names = name === undefined ? [...this.#refs.keys()] : [name];
    for (const n of names) {
      this.#cache.delete(n);
      this.#logger?.info("credential rotated", { credential: n });
      for (const hook of this.#hooks) await hook(n);
    }
  }

  #onSourceSignal(name: string): void {
    // Synchronous signal from a resolver: invalidate now; async hooks wait for a drain.
    this.#cache.delete(name);
    for (const hook of this.#hooks) {
      const result = hook(name);
      if (result instanceof Promise) this.#pending.push(result);
    }
  }

  /** Await async hooks queued by a synchronous RotationSource signal. */
  async drainRotationHooks(): Promise<void> {
    const pending = this.#pending;
    this.#pending = [];
    await Promise.all(pending);
  }
}
