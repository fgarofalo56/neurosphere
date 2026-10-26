import { defineConfig, devices } from "@playwright/test";

const appPort = Number(process.env["NS_E2E_APP_PORT"] ?? 4173);
const apiPort = Number(process.env["NS_MOCK_API_PORT"] ?? 4010);
const appOrigin = `http://127.0.0.1:${appPort}`;
const isCi = process.env["CI"] !== undefined && process.env["CI"] !== "";
// The `visual` project exists only on Linux (or when forced with NS_VISUAL=1).
const visualEnabled = process.platform === "linux" || process.env["NS_VISUAL"] === "1";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: isCi,
  retries: isCi ? 1 : 0,
  reporter: isCi
    ? [["github"], ["html", { open: "never" }], ["line"]]
    : [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: appOrigin,
    trace: "retain-on-failure",
  },
  // Baselines have no platform suffix: they are only valid when rendered by the pinned Linux
  // Playwright image (scripts/update-visual-baselines.mjs).
  snapshotPathTemplate: "{testDir}/__screenshots__/{arg}{ext}",
  projects: [
    {
      name: "chromium",
      // The pixel-comparison spec belongs to the `visual` project only.
      testIgnore: "**/visual/visual.spec.ts",
      use: { ...devices["Desktop Chrome"], headless: true },
    },
    ...(visualEnabled
      ? [
          {
            name: "visual",
            testDir: "./tests/e2e/visual",
            testMatch: "visual.spec.ts",
            use: { ...devices["Desktop Chrome"], headless: true },
          },
        ]
      : []),
  ],
  webServer: [
    {
      command: "node tests/mock-api/server.ts",
      url: `http://127.0.0.1:${apiPort}/api/v1/health`,
      env: { NS_MOCK_API_PORT: String(apiPort), NS_E2E_APP_ORIGIN: appOrigin },
      reuseExistingServer: !isCi,
    },
    {
      command: `pnpm exec vite --mode e2e --host 127.0.0.1 --port ${appPort} --strictPort`,
      url: appOrigin,
      reuseExistingServer: !isCi,
      timeout: 120_000,
    },
  ],
});
