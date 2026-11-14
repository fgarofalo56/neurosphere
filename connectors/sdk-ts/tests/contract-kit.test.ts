// Contract kit pass/fail behaviour, mirroring connectors/sdk-python/tests/test_contract_kit.py.

import { describe, expect, it } from "vitest";

import {
  BaseConnector,
  ConnectorError,
  buildManifest,
  checkConnectorContract,
  validateManifest,
} from "../src/index.js";

function manifest() {
  return buildManifest({
    name: "demo",
    version: "0.1.0",
    capabilities: ["telemetry_ingest", "health_reporting"],
    supportedClouds: ["commercial"],
    granularity: { time_grain: "event", subject_level: "request" },
  });
}

class Conforming extends BaseConnector {
  readonly manifest = manifest();

  constructor() {
    super();
  }
}

const codes = async (connector: unknown): Promise<string[]> =>
  (await checkConnectorContract(connector)).map((v) => v.code);

describe("checkConnectorContract", () => {
  it("passes a conforming connector", async () => {
    expect(await checkConnectorContract(new Conforming())).toEqual([]);
  });

  it("fails a connector with no health()", async () => {
    const connector = { manifest: manifest(), coverage: () => Promise.resolve({}) };
    expect(await codes(connector)).toContain("health_missing");
  });

  it("fails a connector with no manifest", async () => {
    expect(await codes({})).toContain("manifest_missing");
    expect(await codes(null)).toContain("manifest_missing");
  });

  it("fails a connector with no coverage reporting", async () => {
    const good = new Conforming();
    const connector = { manifest: manifest(), health: () => good.health() };
    expect(await codes(connector)).toContain("coverage_missing");
  });

  it("fails an invalid manifest", async () => {
    const good = new Conforming();
    const bad = { ...good.manifest, advisory: false };
    const connector = {
      manifest: bad,
      health: () => good.health(),
      coverage: () => good.coverage(),
      freshness: () => good.freshness(),
    };
    expect(await codes(connector)).toContain("manifest_invalid");
  });

  it("fails a wrong health report type", async () => {
    const good = new Conforming();
    const connector = {
      manifest: good.manifest,
      health: () => Promise.resolve({ state: "healthy" }),
      coverage: () => good.coverage(),
      freshness: () => good.freshness(),
    };
    expect(await codes(connector)).toContain("health_type");
  });
});

describe("SDK hardening (issue 50)", () => {
  it("validateManifest returns a deep-frozen copy and leaves the input alone", () => {
    const input = JSON.parse(JSON.stringify(manifest())) as Record<string, unknown>;
    const out = validateManifest(input);
    expect(out).not.toBe(input);
    expect(Object.isFrozen(out)).toBe(true);
    expect(Object.isFrozen(out.granularity)).toBe(true);
    expect(Object.isFrozen(out.capabilities)).toBe(true);
    expect(Object.isFrozen(input)).toBe(false);
    expect(() => {
      (out as { name: string }).name = "changed";
    }).toThrow(TypeError);
  });

  it("credential() without a broker rejects with a coded ConnectorError", async () => {
    const error: unknown = await new Conforming().credential("api_key").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ConnectorError);
    expect((error as ConnectorError).code).toBe("credential_broker_missing");
  });
});
