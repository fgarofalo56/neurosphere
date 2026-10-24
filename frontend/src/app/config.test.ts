import { describe, expect, it } from "vitest";
import { ConfigError, loadConfig, parseConfig, type FetchLike } from "./config";

const valid = {
  cloud: "government",
  tenantId: "tenant",
  clientId: "client",
  apiBaseUrl: "https://api.example.test",
  apiScope: "api://x/access",
};

function fetchOf(body: unknown, ok = true, status = 200): FetchLike {
  return () => Promise.resolve({ ok, status, json: () => Promise.resolve(body) });
}

describe("parseConfig", () => {
  it("accepts both supported clouds", () => {
    expect(parseConfig(valid).cloud).toBe("government");
    expect(parseConfig({ ...valid, cloud: "commercial" }).cloud).toBe("commercial");
  });

  it("rejects a missing cloud", () => {
    expect(() => parseConfig({ ...valid, cloud: undefined })).toThrow(ConfigError);
  });

  it("rejects an unknown cloud", () => {
    expect(() => parseConfig({ ...valid, cloud: "china" })).toThrow(/cloud/);
  });

  it("rejects empty or missing string fields and lists every problem", () => {
    try {
      parseConfig({ cloud: "commercial", tenantId: "", clientId: 5 });
      expect.unreachable();
    } catch (error) {
      expect(error).toBeInstanceOf(ConfigError);
      expect((error as ConfigError).problems).toHaveLength(4);
    }
  });

  it("rejects non-objects", () => {
    expect(() => parseConfig(null)).toThrow(ConfigError);
    expect(() => parseConfig([])).toThrow(ConfigError);
  });
});

describe("loadConfig", () => {
  it("loads a valid config", async () => {
    await expect(loadConfig(fetchOf(valid), "/config.json", {})).resolves.toMatchObject({
      cloud: "government",
    });
  });

  it("fills gaps from dev defaults but file values win", async () => {
    const config = await loadConfig(
      fetchOf(Object.fromEntries(Object.entries(valid).filter(([key]) => key !== "clientId"))),
      "/config.json",
      { clientId: "dev", tenantId: "ignored" },
    );
    expect(config.clientId).toBe("dev");
    expect(config.tenantId).toBe("tenant");
  });

  it("fails on HTTP errors, bad JSON and unknown cloud", async () => {
    await expect(loadConfig(fetchOf({}, false, 404), "/config.json", {})).rejects.toThrow(/404/);
    const badJson: FetchLike = () =>
      Promise.resolve({ ok: true, status: 200, json: () => Promise.reject(new Error("x")) });
    await expect(loadConfig(badJson, "/config.json", {})).rejects.toThrow(ConfigError);
    await expect(
      loadConfig(fetchOf({ ...valid, cloud: "mars" }), "/config.json", {}),
    ).rejects.toThrow(/cloud/);
  });
});

describe("theme defaults", () => {
  it("accepts a known default pack and mode", () => {
    const config = parseConfig({
      ...valid,
      defaultThemePack: "sample-agency",
      defaultThemeMode: "dark",
    });
    expect(config.defaultThemePack).toBe("sample-agency");
    expect(config.defaultThemeMode).toBe("dark");
  });

  it("leaves them undefined when absent", () => {
    const config = parseConfig(valid);
    expect(config.defaultThemePack).toBeUndefined();
    expect(config.defaultThemeMode).toBeUndefined();
  });

  it("rejects an unknown pack or mode", () => {
    expect(() => parseConfig({ ...valid, defaultThemePack: "nope" })).toThrow(/defaultThemePack/);
    expect(() => parseConfig({ ...valid, defaultThemeMode: "sepia" })).toThrow(/defaultThemeMode/);
  });
});
