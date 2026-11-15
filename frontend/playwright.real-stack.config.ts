import { defineConfig, devices } from "@playwright/test";

/**
 * Real-stack browser run (PRP-29 item 11): MANUAL gate, never part of the PR job.
 *
 * It drives the compose stack (`make stack-up`: nginx edge + api + workers + emulators) with a
 * real Entra sign-in, so there is NO webServer here and no mock API. The default
 * `playwright.config.ts` (testDir `./tests/e2e`) does not see these specs.
 *
 * Run (headed, because a human completes the Entra sign-in in the window that opens):
 *   NS_REAL_STACK_PORT=8080 pnpm --filter @neurosphere/frontend exec \
 *     playwright test -c playwright.real-stack.config.ts --headed
 *
 * The origin is `localhost`, not `127.0.0.1`: Entra allows `http://` SPA redirect URIs only on
 * `localhost`. Chromium still resolves `localhost` to 127.0.0.1 (`LOCALHOST_IPV4`), because
 * `localhost` resolves to `::1` first on Windows and Docker's IPv6 port forward can hang the load.
 */
/**
 * CI mode (PRP-38 item 6, assumption A3): `NS_REAL_STACK_MODE=ci` runs headless with NO human and
 * NO Entra. Two webServers start: the test-only stand-in API (tests/integration/real_stack/
 * serve_stand_in_api.py: the composed API + workers over the emulators, trusting an in-memory dev
 * issuer) and plain `vite` with `/api` proxied to it. global-setup seeds the stack and builds the
 * MSAL session cache from a stand-in token; `/config.json` is answered by the fixtures. Nothing in
 * `src/` changes. Ports: NS_E2E_APP_PORT (default 5300) and NS_STAND_IN_API_PORT (default 8765).
 * The emulators must already be running (`docker compose up -d --wait`).
 */
export const CI_MODE = process.env["NS_REAL_STACK_MODE"] === "ci";
export const STAND_IN_TOKEN_FILE = "test-results/real-stack/stand-in-token.txt";
const appPort = Number(process.env["NS_E2E_APP_PORT"] ?? 5300);
const apiPort = Number(process.env["NS_STAND_IN_API_PORT"] ?? 8765);
const port = CI_MODE ? appPort : Number(process.env["NS_REAL_STACK_PORT"] ?? 8080);
const origin = CI_MODE ? `http://127.0.0.1:${port}` : `http://localhost:${port}`;
export const LOCALHOST_IPV4 = ["--host-resolver-rules=MAP localhost 127.0.0.1"];

export default defineConfig({
  testDir: "./tests/real-stack",
  testMatch: /.*\.spec\.ts/,
  globalSetup: "./tests/real-stack/global-setup.ts",
  // One signed-in session, one page at a time: the stack is shared and the sign-in is manual.
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 90_000,
  ...(CI_MODE
    ? {
        webServer: [
          {
            command: "uv run python ../tests/integration/real_stack/serve_stand_in_api.py",
            cwd: ".",
            url: `http://127.0.0.1:${apiPort}/healthz`,
            env: {
              NS_STAND_IN_API_PORT: String(apiPort),
              NS_STAND_IN_TOKEN_FILE: STAND_IN_TOKEN_FILE,
            },
            reuseExistingServer: false,
            timeout: 180_000,
          },
          {
            command: `pnpm exec vite --host 127.0.0.1 --port ${appPort} --strictPort`,
            url: origin,
            env: { NS_DEV_API_TARGET: `http://127.0.0.1:${apiPort}` },
            reuseExistingServer: false,
            timeout: 120_000,
          },
        ],
      }
    : {}),
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report/real-stack" }]],
  outputDir: "test-results/real-stack",
  use: {
    baseURL: origin,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        headless: CI_MODE,
        launchOptions: { args: CI_MODE ? [] : LOCALHOST_IPV4 },
      },
    },
  ],
});
