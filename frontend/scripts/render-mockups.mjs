/* global process, console, fetch, setTimeout, document */
// PRP-30 item 4: renders the static mockup gallery to docs/design/prp-30/mockups/*.png.
// Starts Vite in demo mode (no mock API needed: the mockups make no API calls), drives Chromium
// at 1440x900 with a fixed clock, UTC, en-US and reduced motion, and always stops Vite on exit.
// Port: NS_MOCKUP_PORT (default 5290). Run from the repo root or frontend/ on Windows or POSIX.
import { spawn } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const frontendDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(frontendDir, "..");
const outDir = join(repoRoot, "docs", "design", "prp-30", "mockups");
const port = Number(process.env["NS_MOCKUP_PORT"] ?? 5290);
if (!Number.isInteger(port) || port < 1024 || port > 65535) {
  console.error("NS_MOCKUP_PORT must be an integer between 1024 and 65535.");
  process.exit(2);
}
const origin = `http://127.0.0.1:${port}`;
const viteBin = join(frontendDir, "node_modules", "vite", "bin", "vite.js");
if (!existsSync(viteBin)) {
  console.error("Vite not found. Run `pnpm install` first.");
  process.exit(2);
}

const PAGES = ["home", "cost-dashboard", "map"];
const STYLES = ["ops-console", "enterprise-fluent"];
const MODES = ["light", "dark"];
const FIXED_TIME = "2026-10-24T12:00:00Z";

let vite = null;

function stopVite() {
  if (vite === null || vite.exitCode !== null || vite.pid === undefined) return;
  if (process.platform === "win32") {
    spawn("taskkill", ["/pid", String(vite.pid), "/T", "/F"], { stdio: "ignore" });
  } else {
    vite.kill("SIGTERM");
  }
}

process.on("exit", stopVite);
process.on("SIGINT", () => process.exit(130));
process.on("SIGTERM", () => process.exit(143));

async function waitFor(url, timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (vite !== null && vite.exitCode !== null) throw new Error("Vite exited early");
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`Vite did not become ready at ${url}`);
}

async function main() {
  mkdirSync(outDir, { recursive: true });
  vite = spawn(
    process.execPath,
    [viteBin, "--mode", "demo", "--host", "127.0.0.1", "--port", String(port), "--strictPort"],
    { cwd: frontendDir, env: { ...process.env }, stdio: ["ignore", "inherit", "inherit"] },
  );
  await waitFor(origin);

  const browser = await chromium.launch();
  try {
    for (const mode of MODES) {
      const context = await browser.newContext({
        viewport: { width: 1440, height: 900 },
        timezoneId: "UTC",
        locale: "en-US",
        reducedMotion: "reduce",
        colorScheme: mode,
      });
      try {
        for (const style of STYLES) {
          for (const page of PAGES) {
            const tab = await context.newPage();
            await tab.clock.setFixedTime(new Date(FIXED_TIME));
            await tab.goto(`${origin}/__mockups/${page}/${style}/${mode}`, {
              waitUntil: "networkidle",
            });
            await tab.waitForSelector("[data-testid='ns-mockup-gallery'] h1", { timeout: 60_000 });
            await tab.evaluate(() => document.fonts.ready);
            await tab.waitForTimeout(400);
            const file = join(outDir, `${page}-${style}-${mode}.png`);
            await tab.screenshot({ path: file, fullPage: true });
            console.log(`[mockups] wrote ${file}`);
            await tab.close();
          }
        }
      } finally {
        await context.close();
      }
    }
  } finally {
    await browser.close();
  }
}

try {
  await main();
  process.exitCode = 0;
} catch (error) {
  console.error("[mockups] failed:", error);
  process.exitCode = 1;
} finally {
  stopVite();
}
