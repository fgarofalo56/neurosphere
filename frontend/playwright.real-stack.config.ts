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
 * The origin is `localhost`, not `127.0.0.1`: the SPA redirect URIs registered on the Entra app
 * are `http://localhost:<port>` and Entra matches them exactly.
 */
const port = Number(process.env["NS_REAL_STACK_PORT"] ?? 8080);
const origin = `http://localhost:${port}`;

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
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report/real-stack" }]],
  outputDir: "test-results/real-stack",
  use: {
    baseURL: origin,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], headless: false } }],
});
