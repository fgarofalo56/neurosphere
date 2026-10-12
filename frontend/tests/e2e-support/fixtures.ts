import { test as base, expect } from "@playwright/test";
import { mockPublicConfig } from "../mock-api/server.ts";

export const MOCK_API_PORT = Number(process.env["NS_MOCK_API_PORT"] ?? 4010);
export const MOCK_API_URL = `http://127.0.0.1:${MOCK_API_PORT}`;

/** Serves the e2e runtime config (apiBaseUrl -> mock API) in place of /config.json. */
export const test = base.extend({
  page: async ({ page }, use) => {
    await page.route("**/config.json", (route) =>
      route.fulfill({ json: mockPublicConfig(MOCK_API_URL) }),
    );
    await use(page);
  },
});

export { expect };
