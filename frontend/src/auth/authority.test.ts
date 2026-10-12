import { describe, expect, it } from "vitest";
import { resolveAuthority } from "./authority";
import { buildMsalConfiguration } from "./msal";
import type { CloudName } from "./config";

const cases: ReadonlyArray<readonly [CloudName, string]> = [
  ["government", "login.microsoftonline.us"],
  ["commercial", "login.microsoftonline.com"],
];

describe("authority by cloud", () => {
  it.each(cases)("%s uses host %s", (cloud, host) => {
    const info = resolveAuthority(cloud, "tenant-1");
    expect(info.host).toBe(host);
    expect(info.authority).toBe(`https://${host}/tenant-1`);
    expect(info.knownAuthorities).toEqual([host]);
  });

  it.each(cases)("%s MSAL config uses sessionStorage and that authority", (cloud, host) => {
    const cfg = buildMsalConfiguration({
      cloud,
      tenantId: "tenant-1",
      clientId: "client-1",
      apiScope: "api://x/.default",
      redirectUri: "https://app.example/",
    });
    expect(new URL(cfg.auth.authority ?? "").host).toBe(host);
    expect(cfg.auth.knownAuthorities).toEqual([host]);
    expect(cfg.cache?.cacheLocation).toBe("sessionStorage");
    expect(cfg.auth.redirectUri).toBe("https://app.example/");
  });

  it("rejects an empty tenant id", () => {
    expect(() => resolveAuthority("commercial", " ")).toThrow();
  });
});
