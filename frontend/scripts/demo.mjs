/* global process, console, fetch, setTimeout */
// Local demo (`pnpm demo`): mock API + Vite in `demo` mode. No Azure, no tenant, no paid calls.
// Ports: NS_DEMO_APP_PORT (default 5180), NS_DEMO_API_PORT (default 5181). Ctrl+C stops both.
// Spawns node directly (no shell) so it behaves the same on Windows and POSIX.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const frontendDir = join(dirname(fileURLToPath(import.meta.url)), "..");
const appPort = Number(process.env["NS_DEMO_APP_PORT"] ?? 5180);
const apiPort = Number(process.env["NS_DEMO_API_PORT"] ?? 5181);
if (!Number.isInteger(appPort) || !Number.isInteger(apiPort) || appPort === apiPort) {
  console.error("NS_DEMO_APP_PORT and NS_DEMO_API_PORT must be two different integers.");
  process.exit(2);
}
const appOrigin = `http://127.0.0.1:${appPort}`;
const apiHealth = `http://127.0.0.1:${apiPort}/api/v1/health`;
const viteBin = join(frontendDir, "node_modules", "vite", "bin", "vite.js");
if (!existsSync(viteBin)) {
  console.error("Vite not found. Run `pnpm install` first.");
  process.exit(2);
}

const children = [];
let stopping = false;

function stop(code) {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    if (child.exitCode === null && child.pid !== undefined) {
      if (process.platform === "win32") {
        spawn("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
      } else {
        child.kill("SIGTERM");
      }
    }
  }
  setTimeout(() => process.exit(code), 500).unref();
}

function start(name, args, env) {
  const child = spawn(process.execPath, args, {
    cwd: frontendDir,
    env: { ...process.env, ...env },
    stdio: ["ignore", "inherit", "inherit"],
  });
  child.on("exit", (code) => {
    if (!stopping) {
      console.error(`[demo] ${name} exited (${code ?? "signal"}); stopping.`);
      stop(1);
    }
  });
  children.push(child);
}

async function waitFor(url, label, timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (stopping) return;
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // not up yet
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  console.error(`[demo] ${label} did not become healthy at ${url}`);
  stop(1);
}

process.on("SIGINT", () => stop(0));
process.on("SIGTERM", () => stop(0));
process.on("exit", () => {
  for (const child of children) if (child.exitCode === null) child.kill();
});

start("mock API", ["tests/mock-api/server.ts"], {
  NS_MOCK_API_PORT: String(apiPort),
  NS_E2E_APP_ORIGIN: appOrigin,
});
start(
  "vite",
  [viteBin, "--mode", "demo", "--host", "127.0.0.1", "--port", String(appPort), "--strictPort"],
  {
    VITE_NS_DEMO_API_PORT: String(apiPort),
  },
);

await waitFor(apiHealth, "mock API");
await waitFor(appOrigin, "vite");
if (!stopping) {
  console.log(`\n[demo] NeuroSphere demo (mock API, synthetic data) ready:\n${appOrigin}\n`);
  console.log("[demo] Press Ctrl+C to stop.");
}
