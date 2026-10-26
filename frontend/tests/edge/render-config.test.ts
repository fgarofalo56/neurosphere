/** PRP-29 item 5: the start-time config.json renderer (POSIX sh, run via child_process). */
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { parseConfig } from "../../src/app/config";

const script = resolve(process.cwd(), "docker", "render-config.sh").replaceAll("\\", "/");
const hasSh = spawnSync("sh", ["-c", "exit 0"]).status === 0;
const suite = hasSh ? describe : describe.skip; // skipped only when no `sh` on PATH

const SECRET_MARKER = "sentinel-value-1234";
const GOOD = {
  NS_UI_CLOUD: "government",
  NS_UI_TENANT_ID: "11111111-1111-1111-1111-111111111111",
  NS_UI_CLIENT_ID: "22222222-2222-2222-2222-222222222222",
  NS_UI_API_SCOPE: "api://22222222-2222-2222-2222-222222222222/access_as_user",
  NS_UI_API_UPSTREAM: "http://api:8000",
};

suite("render-config.sh", () => {
  let dir = "";
  let html = "";
  let out = "";
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "ns-render-")).replaceAll("\\", "/");
    html = `${dir}/html`;
    out = `${dir}/out`;
    mkdirSync(html);
  });
  afterEach(() => rmSync(dir, { recursive: true, force: true }));

  function run(env: Record<string, string>) {
    return spawnSync("sh", [script], {
      encoding: "utf8",
      env: {
        PATH: process.env["PATH"] ?? "",
        NS_UI_HTML_DIR: html,
        NS_UI_CONFIG_OUT_DIR: out,
        NS_UI_HEALTH_OUT_DIR: `${dir}/health`,
        ...env,
      },
    });
  }

  it("renders env to a config.json that parseConfig accepts, with apiBaseUrl '/'", () => {
    const r = run(GOOD);
    expect(r.status).toBe(0);
    const json: unknown = JSON.parse(readFileSync(`${out}/config.json`, "utf8"));
    expect(json).toEqual({
      cloud: "government",
      tenantId: GOOD.NS_UI_TENANT_ID,
      clientId: GOOD.NS_UI_CLIENT_ID,
      apiBaseUrl: "/",
      apiScope: GOOD.NS_UI_API_SCOPE,
    });
    expect(parseConfig(json).apiBaseUrl).toBe("/");
    expect(r.stdout + r.stderr).not.toContain(GOOD.NS_UI_TENANT_ID);
    expect(r.stdout + r.stderr).not.toContain(GOOD.NS_UI_CLIENT_ID);
  });

  it.each([
    "NS_UI_CLOUD",
    "NS_UI_TENANT_ID",
    "NS_UI_CLIENT_ID",
    "NS_UI_API_SCOPE",
    "NS_UI_API_UPSTREAM",
  ])("fails naming %s when it is missing", (name) => {
    const env: Record<string, string> = { ...GOOD };
    delete env[name];
    const r = run(env);
    expect(r.status).not.toBe(0);
    expect(r.stderr).toContain(name);
    expect(existsSync(`${out}/config.json`)).toBe(false);
  });

  it("never prints a rejected value", () => {
    const r = run({ ...GOOD, NS_UI_TENANT_ID: `${SECRET_MARKER}"injected` });
    expect(r.status).not.toBe(0);
    expect(r.stderr).toContain("NS_UI_TENANT_ID");
    expect(r.stdout + r.stderr).not.toContain(SECRET_MARKER);
  });

  it("rejects a bad cloud and a non-http upstream without echoing them", () => {
    const cloud = run({ ...GOOD, NS_UI_CLOUD: SECRET_MARKER });
    expect(cloud.status).not.toBe(0);
    expect(cloud.stderr).toContain("NS_UI_CLOUD");
    expect(cloud.stderr).not.toContain(SECRET_MARKER);
    const up = run({ ...GOOD, NS_UI_API_UPSTREAM: `ftp://${SECRET_MARKER}` });
    expect(up.status).not.toBe(0);
    expect(up.stderr).not.toContain(SECRET_MARKER);
  });

  it("lets a mounted config.json win: nothing rendered, identity vars not required", () => {
    writeFileSync(`${html}/config.json`, "{}");
    const r = run({ NS_UI_API_UPSTREAM: GOOD.NS_UI_API_UPSTREAM });
    expect(r.status).toBe(0);
    expect(existsSync(`${out}/config.json`)).toBe(false);
  });

  describe("health proxy opt-in (NS_UI_PROXY_HEALTH)", () => {
    const readHealth = () => readFileSync(`${dir}/health/health.conf`, "utf8");

    it("writes 404 locations for /readyz and /healthz without the opt-in", () => {
      const r = run({ ...GOOD, NS_UI_HEALTH_OUT_DIR: `${dir}/health` });
      expect(r.status).toBe(0);
      const conf = readHealth();
      expect(conf).toContain("location = /readyz {\n    return 404;");
      expect(conf).toContain("location = /healthz {\n    return 404;");
      expect(conf).not.toContain("proxy_pass");
    });

    it("does not treat a value other than 1 as opt-in", () => {
      const r = run({ ...GOOD, NS_UI_HEALTH_OUT_DIR: `${dir}/health`, NS_UI_PROXY_HEALTH: "true" });
      expect(r.status).toBe(0);
      expect(readHealth()).not.toContain("proxy_pass");
    });

    it("proxies /readyz and /healthz to the upstream with the opt-in", () => {
      const r = run({ ...GOOD, NS_UI_HEALTH_OUT_DIR: `${dir}/health`, NS_UI_PROXY_HEALTH: "1" });
      expect(r.status).toBe(0);
      const conf = readHealth();
      expect(conf).toContain("location = /readyz {\n    proxy_pass http://api:8000;");
      expect(conf).toContain("location = /healthz {\n    proxy_pass http://api:8000;");
      expect(conf).toContain("proxy_set_header Host $proxy_host;");
      expect(conf).not.toContain("return 404");
    });

    it("writes the health include even when a config.json is mounted", () => {
      writeFileSync(`${html}/config.json`, "{}");
      const r = run({
        NS_UI_API_UPSTREAM: GOOD.NS_UI_API_UPSTREAM,
        NS_UI_HEALTH_OUT_DIR: `${dir}/health`,
      });
      expect(r.status).toBe(0);
      expect(existsSync(`${dir}/health/health.conf`)).toBe(true);
    });
  });

  it("still requires the upstream when a config.json is mounted", () => {
    writeFileSync(`${html}/config.json`, "{}");
    const r = run({});
    expect(r.status).not.toBe(0);
    expect(r.stderr).toContain("NS_UI_API_UPSTREAM");
  });
});
