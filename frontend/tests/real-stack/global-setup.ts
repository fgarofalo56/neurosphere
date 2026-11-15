import { spawnSync } from "node:child_process";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { chromium, type FullConfig } from "@playwright/test";
import { CI_MODE, LOCALHOST_IPV4, STAND_IN_TOKEN_FILE } from "../../playwright.real-stack.config";
import { standInConfig } from "./stand-in.ts";

/**
 * Waits for a HUMAN to complete the real Entra sign-in in a headed browser window, then saves
 * the session so every spec starts signed in.
 *
 * MSAL keeps its token cache in `sessionStorage` (`src/auth/msal.ts`), which Playwright's
 * `storageState` does not persist, so the session is dumped to a file and replayed into each new
 * page by `fixtures.ts`. The file holds tokens: it lives under `test-results/` (gitignored) and
 * is deleted by the teardown this function returns.
 */
export const SESSION_FILE = "test-results/real-stack/session-storage.json";
const SIGN_IN_TIMEOUT_MS = 10 * 60_000;

/**
 * CI mode: seed the stack through the stand-in launcher (the API + workers it started run beside
 * the seed, as the compose `workers` service does), then build the MSAL cache from the stand-in
 * token. MSAL's own `loadExternalTokens` writes the cache, so the key shapes are never guessed.
 */
async function ciSetup(baseURL: string): Promise<void> {
  const seeded = spawnSync(
    "uv",
    ["run", "python", "../tests/integration/real_stack/serve_stand_in_api.py", "seed"],
    { stdio: "inherit", timeout: 12 * 60_000, shell: process.platform === "win32" },
  );
  if (seeded.status !== 0) throw new Error(`stack seed failed (exit ${String(seeded.status)})`);
  const token = readFileSync(STAND_IN_TOKEN_FILE, "utf8").trim();
  const appConfig = standInConfig();

  const browser = await chromium.launch({ headless: true });
  try {
    const page = await (await browser.newContext()).newPage();
    await page.route("**/config.json", (route) => route.fulfill({ json: appConfig }));
    await page.goto(baseURL);
    const session = await page.evaluate(
      async ({ cfg, accessToken }) => {
        const { buildMsalConfiguration } = (await import(
          /* @vite-ignore */ "/src/auth/msal.ts"
        )) as typeof import("../../src/auth/msal");
        const msal = (await import(
          /* @vite-ignore */ "/@id/@azure/msal-browser"
        )) as typeof import("@azure/msal-browser");
        const configuration = buildMsalConfiguration({
          cloud: "commercial",
          tenantId: cfg.tenantId,
          clientId: cfg.clientId,
          apiScope: cfg.apiScope,
        });
        const now = Math.floor(Date.now() / 1000);
        await msal.loadExternalTokens(
          configuration,
          {
            scopes: [cfg.apiScope],
            authority: `https://login.microsoftonline.com/${cfg.tenantId}`,
          },
          {
            id_token: accessToken,
            access_token: accessToken,
            token_type: "Bearer",
            scope: cfg.apiScope,
            expires_in: 6 * 3600,
            ext_expires_in: 6 * 3600,
            not_before: now,
          } as never,
          { extendedExpiresOn: now + 6 * 3600 },
        );
        return JSON.stringify(Object.fromEntries(Object.entries(window.sessionStorage)));
      },
      { cfg: appConfig, accessToken: token },
    );
    mkdirSync(dirname(SESSION_FILE), { recursive: true });
    writeFileSync(SESSION_FILE, session, { mode: 0o600 });
  } finally {
    await browser.close();
  }
}

export default async function globalSetup(config: FullConfig): Promise<() => Promise<void>> {
  const baseURL = config.projects[0]?.use.baseURL;
  if (baseURL === undefined) throw new Error("real-stack config has no baseURL");
  if (CI_MODE) {
    await ciSetup(baseURL);
    return async () => {
      rmSync(SESSION_FILE, { force: true });
      rmSync(STAND_IN_TOKEN_FILE, { force: true });
    };
  }

  const browser = await chromium.launch({ headless: false, args: LOCALHOST_IPV4 });
  try {
    const page = await (await browser.newContext()).newPage();
    // Registered before the first navigation: the answer arrives only after the redirect round
    // trip through Entra and back, once the app holds a token and asks who the caller is.
    const signedIn = page.waitForResponse(
      (response) => response.url().includes("/api/v1/me/domains") && response.status() === 200,
      { timeout: SIGN_IN_TIMEOUT_MS },
    );
    await page.goto(baseURL);
    console.log(`Sign in with your Entra account in the open browser window (${baseURL}).`);
    await signedIn;
    const session = await page.evaluate(() =>
      JSON.stringify(Object.fromEntries(Object.entries(window.sessionStorage))),
    );
    mkdirSync(dirname(SESSION_FILE), { recursive: true });
    writeFileSync(SESSION_FILE, session, { mode: 0o600 });
  } finally {
    await browser.close();
  }
  return async () => {
    rmSync(SESSION_FILE, { force: true });
  };
}
