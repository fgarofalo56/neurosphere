/**
 * PRP-28 item 3: the local demo mode must never reach a production artifact.
 * 1. A real production `vite build` (programmatic, temp outDir) contains no demo/stub markers.
 * 2. No deploy artifact (Dockerfile, nginx.conf, Helm chart) mentions a demo flag.
 * Plain substring checks only; no HTML parsing.
 */
import { mkdtempSync, readdirSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { build } from "vite";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

// vitest runs with cwd = frontend (pnpm --filter / CI working-directory).
const frontendDir = process.cwd();
const repoRoot = resolve(frontendDir, "..");

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
  '"demo"', // the demo mode branch comparison
  "__ns_mockups__", // PRP-30 mockup gallery marker
  "ns-mockup-gallery", // PRP-30 mockup gallery test id
] as const;

const DEMO_FLAGS = [
  "--mode demo",
  "MODE=demo",
  "NS_DEMO",
  "VITE_NS_DEMO",
  "pnpm demo",
  "pnpm run demo",
] as const;

describe("production build excludes demo mode", () => {
  let outDir = "";
  beforeAll(async () => {
    outDir = mkdtempSync(join(tmpdir(), "ns-prod-build-"));
    await build({
      root: frontendDir,
      configFile: false,
      mode: "production",
      logLevel: "silent",
      plugins: [react()],
      build: { outDir, emptyOutDir: true, reportCompressedSize: false },
    });
  }, 300_000);
  afterAll(() => {
    if (outDir !== "") rmSync(outDir, { recursive: true, force: true });
  });

  it("emits no demo banner, stub sign-in or demo-mode branch", () => {
    const files = listFiles(outDir).filter((f) => /\.(js|mjs|html|css)$/.test(f));
    expect(files.length).toBeGreaterThan(0);
    const offenders: string[] = [];
    for (const file of files) {
      const text = readFileSync(file, "utf8");
      for (const marker of FORBIDDEN_BUILD_MARKERS) {
        if (text.includes(marker))
          offenders.push(`${file.slice(outDir.length)} contains ${marker}`);
      }
    }
    expect(offenders).toEqual([]);
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
