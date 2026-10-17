import { inspect } from "node:util";
import { describe, expect, it } from "vitest";

import * as sdk from "../src/index.js";
import {
  BaseConnector,
  CredentialBroker,
  HealthTracker,
  InvalidManifestError,
  RateLimitedError,
  SecretValue,
  StaticCredentialResolver,
  buildManifest,
  checkConnectorContract,
  coverageFraction,
  makeCoverage,
  manifestIssues,
  validateManifest,
} from "../src/index.js";

const GRAIN = { time_grain: "event", subject_level: "request" } as const;
const REF = { name: "api_key", vault_ref: "https://demo.vault.azure.net/secrets/api-key" };
// Generated per run so no secret-shaped literal sits in the repo.
const SECRET = `fixture-${globalThis.crypto.randomUUID()}`;

describe("export surface", () => {
  it("has no write API", () => {
    const names = Object.keys(sdk);
    expect(names.length).toBeGreaterThan(0);
    for (const name of names) {
      expect(name).not.toMatch(/write|apply|rollback|dry_?run/i);
    }
    expect(names).toContain("BaseConnector");
  });
});

describe("manifest", () => {
  it("builds read-only advisory manifests with unknowns as null", () => {
    const m = buildManifest({
      name: "demo",
      version: "1.0.0",
      capabilities: ["telemetry_ingest"],
      supportedClouds: ["commercial"],
      granularity: GRAIN,
    });
    expect(m.advisory).toBe(true);
    expect(m.write_support).toEqual({ supported: false, actions: [] });
    expect(m.freshness).toEqual({ typical_delay_ms: null, max_delay_ms: null });
    expect(m.rate_limits).toBeNull();
    expect(m.auth_mode).toBe("managed_identity");
  });

  it("derives vault_reference when refs are given", () => {
    const m = buildManifest({
      name: "demo",
      version: "1.0.0",
      capabilities: ["cost_ingest"],
      supportedClouds: ["commercial"],
      granularity: GRAIN,
      credentialRefs: [REF],
    });
    expect(m.auth_mode).toBe("vault_reference");
  });

  it("rejects a vault host outside the listed clouds", () => {
    expect(() =>
      buildManifest({
        name: "demo",
        version: "1.0.0",
        capabilities: ["cost_ingest"],
        supportedClouds: ["government"],
        granularity: GRAIN,
        credentialRefs: [REF],
      }),
    ).toThrow(InvalidManifestError);
  });

  it("rejects duplicate credential names, schema violations and bad JSON", () => {
    const base = buildManifest({
      name: "demo",
      version: "1.0.0",
      capabilities: ["cost_ingest"],
      supportedClouds: ["commercial"],
      granularity: GRAIN,
      credentialRefs: [REF],
    });
    const dup = { ...base, credential_refs: [REF, REF] };
    expect(manifestIssues(dup).map((i) => i.pointer)).toContain("/credential_refs/1/name");
    expect(manifestIssues({ ...base, extra: 1 }).length).toBeGreaterThan(0);
    expect(manifestIssues({ ...base, name: "Bad Name" }).length).toBeGreaterThan(0);
    expect(manifestIssues("{nope")).toEqual([{ pointer: "", detail: "document is not valid JSON" }]);
    expect(manifestIssues("[]")[0]?.detail).toBe("document must be a JSON object");
  });

  it("applies the schema if/then rules", () => {
    const base = buildManifest({
      name: "demo",
      version: "1.0.0",
      capabilities: ["cost_ingest"],
      supportedClouds: ["commercial"],
      granularity: GRAIN,
    });
    expect(manifestIssues({ ...base, advisory: false }).length).toBeGreaterThan(0);
    expect(
      manifestIssues({ ...base, capabilities: ["cost_ingest", "action_execution"] }).length,
    ).toBeGreaterThan(0);
    expect(manifestIssues({ ...base, credential_refs: [REF] }).length).toBeGreaterThan(0);
  });

  it("issue text never echoes submitted values", () => {
    const issues = manifestIssues({ name: SECRET, version: SECRET });
    expect(JSON.stringify(issues)).not.toContain(SECRET);
  });
});

describe("health", () => {
  const t0 = new Date("2026-01-01T00:00:00Z");

  it("is unknown before any call, with null (never 0) measurements", () => {
    const r = new HealthTracker({ clock: () => t0 }).snapshot();
    expect(r.state).toBe("unknown");
    expect(r.freshness.lagMs).toBeNull();
    expect(r.coverage.expectedSources).toBeNull();
    expect(r.rateLimit.remaining).toBeNull();
    expect(coverageFraction(r.coverage)).toBeNull();
  });

  it("maps rate limiting, hard failures and recovery", () => {
    let now = t0;
    const tracker = new HealthTracker({ clock: () => now });
    tracker.recordError(new RateLimitedError(30));
    let r = tracker.snapshot();
    expect(r.state).toBe("rate_limited");
    expect(r.rateLimit.retryAfterSeconds).toBe(30);
    now = new Date(t0.getTime() + 31_000);
    expect(tracker.snapshot().rateLimit.limited).toBe(false);
    tracker.recordError(new Error("boom with a body that must not be copied"));
    r = tracker.snapshot();
    expect(r.state).toBe("failing");
    expect(r.lastErrorCode).toBe("internal_error");
    expect(JSON.stringify(r)).not.toContain("boom");
    tracker.recordSuccess({ coverage: makeCoverage({ expectedSources: 4, answeredSources: 3 }) });
    r = tracker.snapshot();
    expect(r.state).toBe("healthy");
    expect(coverageFraction(r.coverage)).toBe(0.75);
  });

  it("rejects coverage with answered above expected", () => {
    expect(() => makeCoverage({ expectedSources: 1, answeredSources: 2 })).toThrow(RangeError);
  });
});

describe("secrets", () => {
  it("SecretValue never reveals through string, JSON or inspect", () => {
    const s = new SecretValue(SECRET);
    for (const out of [
      String(s),
      `${s}`,
      s.toString(),
      JSON.stringify({ s }),
      inspect(s),
      inspect({ nested: [s] }),
    ]) {
      expect(out).not.toContain(SECRET);
    }
    expect(s.reveal()).toBe(SECRET);
    expect(s.equals(new SecretValue(SECRET))).toBe(true);
    expect(s.equals(new SecretValue("other"))).toBe(false);
  });

  it("broker resolves, caches and picks up a rotation without restart", async () => {
    const resolver = new StaticCredentialResolver({ [REF.vault_ref]: "v1" });
    const broker = new CredentialBroker(resolver, [REF]);
    const seen: string[] = [];
    broker.onRotation(async (name) => {
      await Promise.resolve();
      seen.push(name);
    });
    expect((await broker.get("api_key")).reveal()).toBe("v1");
    resolver.rotate(REF, "v2");
    await broker.drainRotationHooks();
    expect(seen).toEqual(["api_key"]);
    expect((await broker.get("api_key")).reveal()).toBe("v2");
    await broker.notifyRotated("api_key");
    expect(seen).toEqual(["api_key", "api_key"]);
  });

  it("errors carry the name only", async () => {
    const broker = new CredentialBroker(new StaticCredentialResolver({}), [REF]);
    await expect(broker.get("api_key")).rejects.toThrow("credential 'api_key' could not be resolved");
    await expect(broker.get("missing")).rejects.toMatchObject({ code: "capability_unavailable" });
  });
});

class Demo extends BaseConnector {
  readonly manifest = buildManifest({
    name: "demo",
    version: "1.0.0",
    capabilities: ["telemetry_ingest"],
    supportedClouds: ["commercial"],
    granularity: GRAIN,
    credentialRefs: [REF],
  });

  constructor(broker?: CredentialBroker) {
    super(broker ? { credentials: broker } : {});
  }
}

describe("BaseConnector and contract check", () => {
  it("passes a conforming connector and records guarded calls", async () => {
    const broker = new CredentialBroker(new StaticCredentialResolver({ [REF.vault_ref]: "v1" }), [
      REF,
    ]);
    const c = new Demo(broker);
    expect(await checkConnectorContract(c)).toEqual([]);
    expect((await c.credential("api_key")).reveal()).toBe("v1");
    await c.guardedCall(() => Promise.resolve(1), {
      freshness: () => ({ lagMs: 5, watermark: null, observedAt: new Date() }),
    });
    expect((await c.freshness()).lagMs).toBe(5);
    expect((await c.health()).state).toBe("healthy");
    await expect(
      c.guardedCall(() => Promise.reject(new RateLimitedError(10))),
    ).rejects.toBeInstanceOf(RateLimitedError);
    expect((await c.health()).state).toBe("rate_limited");
    await c.close();
    expect(c.closed).toBe(true);
  });

  it("flags missing manifest, health and coverage without throwing", async () => {
    const codes = (await checkConnectorContract({})).map((v) => v.code);
    expect(codes).toEqual(
      expect.arrayContaining(["manifest_missing", "health_missing", "coverage_missing"]),
    );
    expect((await checkConnectorContract(null))[0]?.code).toBe("manifest_missing");
  });

  it("flags an invalid manifest and unknown-as-zero freshness", async () => {
    const bad = {
      manifest: { name: "x" },
      health: () => Promise.resolve(new HealthTracker().snapshot()),
      coverage: () => Promise.resolve(makeCoverage({})),
      freshness: () => Promise.resolve({ lagMs: 0, watermark: null, observedAt: null }),
    };
    const codes = (await checkConnectorContract(bad)).map((v) => v.code);
    expect(codes).toContain("manifest_invalid");
    expect(codes).toContain("freshness_unknown_as_zero");
  });

  it("validateManifest accepts a built manifest", () => {
    expect(validateManifest(new Demo().manifest).name).toBe("demo");
  });
});
