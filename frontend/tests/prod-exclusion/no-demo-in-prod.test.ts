/**
 * PRP-28 item 3 + PRP-47 item 4: the local demo mode must never reach a production artifact.
 * 1. A real production `vite build` (programmatic, temp outDir, the real vite.config.ts with the
 *    bundle-report plugin off) contains no demo/stub markers.
 * 2. Positive control: the same build with `mode: "demo"` DOES contain the demo markers, so a
 *    string that is renamed in the source cannot turn check 1 into a silent pass.
 * 3. No deploy artifact (Dockerfile, nginx.conf, Helm chart) mentions a demo flag.
 * 4. The mock API binds loopback only.
 * Plain substring checks only; no HTML parsing.
 *
 * Note (#93): the repo `.gitignore` has a bare `build/` rule. It would also hide any directory
 * named `build` under the frontend, so build output goes to a temp outDir and no source
 * directory may be called `build`.
 */
import { mkdtempSync, readdirSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { build, loadConfigFromFile, type InlineConfig, type PluginOption } from "vite";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

// import.meta.dirname is this file's directory (frontend/tests/prod-exclusion), not the cwd.
const frontendDir = resolve(import.meta.dirname, "..", "..");
const repoRoot = resolve(frontendDir, "..");
const BUNDLE_REPORT_PLUGIN = "ns-bundle-report";

function listFiles(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) out.push(...listFiles(full));
    else out.push(full);
  }
  return out;
}

// Distinctive strings that exist only in demo-mode or stub-sign-in code.
const FORBIDDEN_BUILD_MARKERS = [
  "Demo data, mock API", // DemoBanner text
  "demo-banner", // DemoBanner test id
  "VITE_NS_DEMO_API_PORT", // demo config env var
  "ns-e2e-fake-token", // stubMsal token prefix
  "e2e.user@example.invalid", // stubMsal account
  "e2e-home-account", // stubMsal account id
  "__ns_mockups__", // PRP-30 mockup gallery marker
  "ns-mockup-gallery", // PRP-30 mockup gallery test id
  "/__mockups/", // PRP-30 mockup route prefix
] as const;

// Positive control: a demo build must carry these (they identify demo mode itself).
const DEMO_ONLY_MARKERS = ["Demo data, mock API", "ns-e2e-fake-token"] as const;

const DEMO_FLAGS = [
  "--mode demo",
  "MODE=demo",
  "NS_DEMO",
  "VITE_NS_DEMO",
  "pnpm demo",
  "pnpm run demo",
] as const;

/** Drops one named plugin from a (possibly nested) plugin list. */
function withoutPlugin(plugins: PluginOption, name: string): PluginOption[] {
  const kept: PluginOption[] = [];
  for (const plugin of [plugins].flat(Infinity) as PluginOption[]) {
    if (typeof plugin === "object" && plugin !== null && "name" in plugin && plugin.name === name) {
      continue;
    }
    kept.push(plugin);
  }
  return kept;
}

/** Builds the real vite.config.ts in `mode` into `outDir`, without the bundle-report side effect. */
async function buildReal(mode: "production" | "demo", outDir: string): Promise<void> {
  const loaded = await loadConfigFromFile(
    { command: "build", mode },
    join(frontendDir, "vite.config.ts"),
    frontendDir,
  );
  if (loaded === null) throw new Error("vite.config.ts not found");
  const config: InlineConfig = {
    ...loaded.config,
    root: frontendDir,
    configFile: false,
    mode,
    logLevel: "silent",
    plugins: withoutPlugin(loaded.config.plugins ?? [], BUNDLE_REPORT_PLUGIN),
    build: { outDir, emptyOutDir: true, reportCompressedSize: false },
  };
  await build(config);
}

function bundleText(outDir: string): { file: string; text: string }[] {
  return listFiles(outDir)
    .filter((f) => /\.(js|mjs|html|css)$/.test(f))
    .map((file) => ({ file: file.slice(outDir.length), text: readFileSync(file, "utf8") }));
}

describe("production build excludes demo mode", () => {
  let prodDir = "";
  let demoDir = "";
  beforeAll(async () => {
    prodDir = mkdtempSync(join(tmpdir(), "ns-prod-build-"));
    demoDir = mkdtempSync(join(tmpdir(), "ns-demo-build-"));
    await buildReal("production", prodDir);
    await buildReal("demo", demoDir);
  }, 600_000);
  afterAll(() => {
    for (const dir of [prodDir, demoDir]) {
      if (dir !== "") rmSync(dir, { recursive: true, force: true });
    }
  });

  it("emits no demo banner, stub sign-in or demo-mode branch", () => {
    const files = bundleText(prodDir);
    expect(files.length).toBeGreaterThan(0);
    const offenders: string[] = [];
    for (const { file, text } of files) {
      for (const marker of FORBIDDEN_BUILD_MARKERS) {
        if (text.includes(marker)) offenders.push(`${file} contains ${marker}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("positive control: the demo build contains the demo markers", () => {
    const text = bundleText(demoDir)
      .map((f) => f.text)
      .join("\n");
    for (const marker of DEMO_ONLY_MARKERS) expect(text).toContain(marker);
  });
});

describe("mock API", () => {
  it("binds the loopback address only", () => {
    const source = readFileSync(join(frontendDir, "tests", "mock-api", "server.ts"), "utf8");
    expect(source).toContain('server.listen(port, "127.0.0.1"');
  });
});

describe("deploy artifacts carry no demo flag", () => {
  const targets = [
    join(frontendDir, "Dockerfile"),
    join(frontendDir, "nginx.conf"),
    ...listFiles(join(repoRoot, "infra", "helm")),
  ];

  it("finds the artifacts it is meant to check", () => {
    expect(targets.length).toBeGreaterThan(2);
  });

  it.each(targets.map((t) => [t.slice(repoRoot.length + 1).replaceAll("\\", "/"), t]))(
    "%s has no demo flag",
    (_label, file) => {
      const text = readFileSync(file as string, "utf8");
      for (const flag of DEMO_FLAGS) expect(text.includes(flag)).toBe(false);
    },
  );
});
