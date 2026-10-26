import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { chromium, type FullConfig } from "@playwright/test";
import { LOCALHOST_IPV4 } from "../../playwright.real-stack.config";

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

export default async function globalSetup(config: FullConfig): Promise<() => Promise<void>> {
  const baseURL = config.projects[0]?.use.baseURL;
  if (baseURL === undefined) throw new Error("real-stack config has no baseURL");

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
