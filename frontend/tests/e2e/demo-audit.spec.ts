import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";

/**
 * PRP-30 item 5: the local demo shows data on every route on a first visit.
 *
 * The spec starts its OWN demo-mode app and mock API (profile `demo`) on ports of its own, so
 * `playwright.config.ts` is untouched and the default e2e servers are not involved. Every route in
 * `route-manifest.json` is visited (detail routes through a link on their list page), with no
 * forbidden state and no empty state on first load. The first landing must be Finance.
 *
 * The demo profile enriches DATA only; authorization is identical to the default profile. The demo
 * persona is Steward, so the routes in `EXPECTED_FORBIDDEN` must show the access-denied state.
 */

const APP_PORT = Number(process.env["NS_DEMO_AUDIT_APP_PORT"] ?? 5318);
const API_PORT = Number(process.env["NS_DEMO_AUDIT_API_PORT"] ?? 5319);
const APP_ORIGIN = `http://127.0.0.1:${APP_PORT}`;
const API_HEALTH = `http://127.0.0.1:${API_PORT}/api/v1/health`;

const frontendDir = process.cwd();
const manifest = JSON.parse(
  readFileSync(join(frontendDir, "src", "app", "route-manifest.json"), "utf8"),
) as { routes: string[] };

/** Detail routes are reached through a link on their list page, not typed in. */
const DETAIL_VIA: Readonly<Record<string, { list: string; link: string }>> = {
  "/actions/detail": { list: "/actions", link: 'a[href*="/actions/detail"]' },
  "/actions/propose": { list: "/actions", link: 'a[href*="/actions/propose"]' },
  "/recommendations/detail": {
    list: "/recommendations",
    link: 'a[href*="/recommendations/detail"]',
  },
  "/reports/view": { list: "/reports", link: 'a[href*="/reports/view"]' },
  "/review/item": { list: "/review", link: 'a[href*="/review/item"]' },
  "/mcp-admin/server": { list: "/mcp-admin", link: 'a[href*="/mcp-admin/server"]' },
};

/**
 * Routes the Steward persona legitimately cannot open, matching the authorization the real API
 * enforces (and the mock reproduces in every profile):
 *  - MCP admin list and detail need `config.manage`, which only Admin holds.
 *  - A workspace is open only to its own persona, so every workspace but Steward's is denied.
 * The audit asserts the forbidden state IS shown here, and fails if one of these ever renders
 * data, so this list cannot rot silently.
 */
const EXPECTED_FORBIDDEN: ReadonlySet<string> = new Set([
  "/mcp-admin",
  "/mcp-admin/server",
  "/workspaces/admin",
  "/workspaces/analyst",
  "/workspaces/auditor",
  "/workspaces/viewer",
]);

/** The detail page needs an id in the URL; the denied list page has no link to follow. */
const FORBIDDEN_DIRECT_URL: Readonly<Record<string, string>> = {
  "/mcp-admin/server": "/mcp-admin/server?server_id=srv-demo",
};

const children: ChildProcess[] = [];

function startChild(args: string[], env: Record<string, string>): void {
  const child = spawn(process.execPath, args, {
    cwd: frontendDir,
    env: { ...process.env, ...env },
    stdio: "ignore",
    windowsHide: true,
  });
  children.push(child);
}

function killChildren(): void {
  for (const child of children) {
    if (child.exitCode !== null || child.pid === undefined) continue;
    if (process.platform === "win32") {
      // Kills the whole tree: vite can spawn helpers that a plain kill() would orphan.
      spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
    } else {
      child.kill("SIGTERM");
    }
  }
  children.length = 0;
}

async function waitFor(url: string, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // not up yet
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error(`${url} did not become healthy within ${timeoutMs} ms`);
}

/** Waits for the page to stop loading: network idle, no skeletons, still idle. */
async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle");
  await expect.soft(page.locator('[data-slot="loading-state"]')).toHaveCount(0);
  await expect.soft(page.getByRole("main")).toBeVisible();
  await page.waitForLoadState("networkidle");
}

async function assertPopulated(page: Page, route: string): Promise<void> {
  await settle(page);
  await expect
    .soft(page.locator('[data-testid="forbidden-state"]'), `${route}: forbidden`)
    .toHaveCount(0);
  await expect.soft(page.locator('[data-slot="empty-state"]'), `${route}: empty`).toHaveCount(0);
  await expect.soft(page.locator('[data-testid="error-state"]'), `${route}: error`).toHaveCount(0);
}

async function assertForbidden(page: Page, route: string): Promise<void> {
  await settle(page);
  await expect
    .soft(page.locator('[data-testid="forbidden-state"]'), `${route}: expected forbidden`)
    .toHaveCount(1);
}

test.describe("demo route audit", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(120_000);

  test.beforeAll(async () => {
    test.setTimeout(180_000);
    const viteBin = join(frontendDir, "node_modules", "vite", "bin", "vite.js");
    if (!existsSync(viteBin)) throw new Error("Vite not found; run pnpm install first.");
    process.once("exit", killChildren);
    try {
      startChild(["tests/mock-api/server.ts"], {
        NS_MOCK_API_PORT: String(API_PORT),
        NS_E2E_APP_ORIGIN: APP_ORIGIN,
        NS_MOCK_PROFILE: "demo",
      });
      startChild(
        [
          viteBin,
          "--mode",
          "demo",
          "--host",
          "127.0.0.1",
          "--port",
          String(APP_PORT),
          "--strictPort",
        ],
        { VITE_NS_DEMO_API_PORT: String(API_PORT) },
      );
      await waitFor(API_HEALTH, 60_000);
      await waitFor(APP_ORIGIN, 120_000);
    } catch (error) {
      killChildren();
      throw error;
    }
  });

  test.afterAll(() => {
    killChildren();
  });

  test("the first landing is the Finance domain", async ({ page }) => {
    await page.goto(`${APP_ORIGIN}/`);
    await settle(page);
    await expect(page.getByRole("combobox", { name: "Domain" })).toContainText("Finance");
    await expect(page.getByTestId("demo-banner")).toBeVisible();
    await expect(page.getByRole("button", { name: "Account: Steward" })).toBeVisible();
  });

  // One test, soft assertions: every route is reported in a single run instead of the first
  // failure hiding the rest.
  test("every manifest route shows data or the honest forbidden state", async ({ page }) => {
    test.setTimeout(manifest.routes.length * 30_000);
    for (const route of manifest.routes) {
      await test.step(route, async () => {
        if (EXPECTED_FORBIDDEN.has(route)) {
          await page.goto(`${APP_ORIGIN}${FORBIDDEN_DIRECT_URL[route] ?? route}`);
          await assertForbidden(page, route);
          return;
        }
        const via = DETAIL_VIA[route];
        if (via === undefined) {
          await page.goto(`${APP_ORIGIN}${route}`);
          await assertPopulated(page, route);
          return;
        }
        await page.goto(`${APP_ORIGIN}${via.list}`);
        await assertPopulated(page, via.list);
        const link = page.locator(via.link).first();
        await expect.soft(link, `${route}: no link on ${via.list}`).toBeVisible();
        if (!(await link.isVisible())) return;
        await link.click();
        await expect.soft(page).toHaveURL(new RegExp(route));
        await assertPopulated(page, route);
      });
    }
  });
});
