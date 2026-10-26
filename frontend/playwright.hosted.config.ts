import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";

/**
 * Hosted-demo browser run (PRP-32 item 6): MANUAL gate, never part of the PR job.
 *
 * It drives the deployed frontend (`https://<prefix>-ui.azurewebsites.net`) as a signed-in
 * operator, so there is NO webServer and no mock API, and nothing is reused from a local server.
 * The default `playwright.config.ts` (testDir `./tests/e2e`) does not see these specs.
 *
 * Run:
 *   NS_HOSTED_URL=https://<frontend-host> pnpm --filter @neurosphere/frontend exec \
 *     playwright test -c playwright.hosted.config.ts
 *
 * Inputs (both required; `tests/hosted/global-setup.ts` refuses to run without them, while
 * `--list` works offline because it never runs global setup):
 *   NS_HOSTED_URL                  base URL of the deployed frontend
 *   temp/hosted-demo/auth.json     Playwright storageState (gitignored, holds tokens, never committed)
 * Optional: temp/hosted-demo/session-storage.json, the MSAL `sessionStorage` dump, replayed into
 * each page (MSAL keeps its cache in sessionStorage, which storageState does not carry).
 */
export const AUTH_STATE_FILE = fileURLToPath(
  new URL("../temp/hosted-demo/auth.json", import.meta.url),
);
export const SESSION_STORAGE_FILE = fileURLToPath(
  new URL("../temp/hosted-demo/session-storage.json", import.meta.url),
);

export default defineConfig({
  testDir: "./tests/hosted",
  testMatch: /.*\.spec\.ts/,
  globalSetup: "./tests/hosted/global-setup.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 120_000,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report/hosted" }]],
  outputDir: "test-results/hosted",
  use: {
    baseURL: process.env["NS_HOSTED_URL"],
    storageState: AUTH_STATE_FILE,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
