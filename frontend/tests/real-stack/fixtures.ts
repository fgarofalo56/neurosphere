import { readFileSync } from "node:fs";
import { test as base, expect, type Page, type Response } from "@playwright/test";
import { SESSION_FILE } from "./global-setup.ts";

/** One API answer seen by the page while a route was open. */
export interface ApiAnswer {
  readonly method: string;
  readonly path: string;
  readonly status: number;
}

export interface RouteVisit {
  readonly page: Page;
  /** Every `/api/` response seen so far (path without the query string). */
  readonly answers: readonly ApiAnswer[];
}

/** Restores the saved MSAL `sessionStorage` into each new document of this origin. */
async function restoreSession(page: Page): Promise<void> {
  const entries = JSON.parse(readFileSync(SESSION_FILE, "utf8")) as Record<string, string>;
  await page.addInitScript((saved: Record<string, string>) => {
    for (const [key, value] of Object.entries(saved)) {
      if (window.sessionStorage.getItem(key) === null) window.sessionStorage.setItem(key, value);
    }
  }, entries);
}

export const test = base.extend<{ visit: RouteVisit }>({
  visit: async ({ page }, use) => {
    await restoreSession(page);
    const answers: ApiAnswer[] = [];
    page.on("response", (response: Response) => {
      const url = new URL(response.url());
      if (!url.pathname.startsWith("/api/")) return;
      answers.push({
        method: response.request().method(),
        path: url.pathname,
        status: response.status(),
      });
    });
    await use({ page, answers });
  },
});

export { expect };
