// @vitest-environment node
/** PRP-29 item 5: the Vite dev proxy is same-origin plumbing for plain `vite` only. */
import { describe, expect, it } from "vitest";
import type { ConfigEnv, UserConfig, UserConfigFnObject } from "vite";
import config from "../../vite.config";

function resolveFor(env: ConfigEnv): UserConfig {
  return (config as UserConfigFnObject)(env);
}

const serve = (mode: string): ConfigEnv => ({ command: "serve", mode });

describe("vite dev proxy", () => {
  it("proxies /api (with WebSocket upgrade), /readyz and /healthz in plain dev", () => {
    const proxy = resolveFor(serve("development")).server?.proxy ?? {};
    expect(Object.keys(proxy).sort()).toEqual(["/api", "/healthz", "/readyz"]);
    const api = proxy["/api"] as { ws?: boolean; target?: string };
    expect(api.ws).toBe(true);
    expect(api.target).toBe(process.env["NS_DEV_API_TARGET"] ?? "http://127.0.0.1:8000");
  });

  it.each(["e2e", "demo", "test"])("applies no proxy in %s mode", (mode) => {
    expect(resolveFor(serve(mode)).server?.proxy).toBeUndefined();
  });

  it("applies no proxy for a production build", () => {
    expect(resolveFor({ command: "build", mode: "production" }).server?.proxy).toBeUndefined();
  });

  it("leaves the vitest configuration intact", () => {
    const test = resolveFor(serve("test")).test;
    expect(test?.environment).toBe("jsdom");
    expect(test?.include).toContain("tests/**/*.test.{ts,tsx}");
  });
});
