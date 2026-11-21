import type { Page } from "@playwright/test";
import { expect, test } from "../../e2e-support/fixtures.ts";
import { DOMAIN_OK } from "../../mock-api/server.ts";
import {
  ACCESS_ASSET_EMPTY,
  ACCESS_ASSET_FORBIDDEN,
  ACCESS_ASSET_LEDGER,
  ACCESS_ASSET_TRUNCATED,
  ACCESS_NODE_FORBIDDEN,
  ACCESS_NODE_SERVICE,
} from "../../mock-api/features/catalog-access.ts";
import {
  analyze,
  blocking,
  describeBlocking,
  MODES,
  seedPreferences,
} from "../a11y/axe-support.ts";

// PRP-73 item 6: the data access page against the mock API (synthetic data). The stub caller is
// a Viewer, which holds data.read. The page is opened through the navigation entry.

const D = encodeURIComponent(DOMAIN_OK);

async function openFromNav(page: Page): Promise<void> {
  await page.goto(`/catalog?domain_id=${D}`);
  await page.getByRole("link", { name: "Data access" }).first().click();
  await expect(page).toHaveURL(/\/catalog\/access/);
  await expect(page.getByRole("heading", { level: 1, name: "Data access" })).toBeVisible();
}

async function pickAsset(page: Page, id: string): Promise<void> {
  const select = page.getByTestId("question-writes").getByLabel("Data asset");
  // The picker fills from the entities list; wait for the option to exist before choosing it.
  await expect(select.locator(`option[value="${id}"]`)).toHaveCount(1);
  await select.selectOption(id);
}

async function askWriters(page: Page, id: string): Promise<void> {
  await pickAsset(page, id);
  await page.getByTestId("run-writes").click();
}

test("who writes: the compliance officer sees writers with status, confidence and evidence", async ({
  page,
}) => {
  await openFromNav(page);
  await askWriters(page, ACCESS_ASSET_LEDGER);
  const rows = page.getByTestId("access-row");
  await expect(rows).toHaveCount(2);
  const budget = rows.filter({ hasText: "Budget bot" });
  await expect(budget).toContainText("Asserted");
  await expect(budget).toContainText("95%");
  await expect(budget).toContainText("trace:a1");
  await expect(budget).toContainText("trace:a2");
  const inferred = rows.filter({ hasText: "Sample agent" });
  await expect(inferred).toContainText("Inferred");
  await expect(inferred).toContainText("trace:b1");
  await expect(page.getByTestId("partial-banner")).toHaveCount(0);
  await page.screenshot({ path: "../temp/prp73-access-page.png", fullPage: true });
});

test("the sensitivity question returns the same result shape", async ({ page }) => {
  await openFromNav(page);
  const panel = page.getByTestId("question-sensitivity");
  await panel.getByLabel("Asset is flagged as containing personal data").check();
  await page.getByTestId("run-sensitivity").click();
  await expect(page.getByTestId("result-summary")).toBeVisible();
  const row = page.getByTestId("access-row").first();
  await expect(row).toContainText(/Asserted|Inferred|Curated/);
  await expect(page.getByRole("columnheader", { name: "Confidence" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Evidence" })).toBeVisible();
});

test("the region group question returns the same result shape", async ({ page }) => {
  await openFromNav(page);
  const select = page.getByTestId("question-region").getByLabel("Region group");
  await expect(select.locator('option[value="eu"]')).toHaveCount(1);
  await select.selectOption("eu");
  await page.getByTestId("run-region").click();
  await expect(page.getByTestId("result-summary")).toBeVisible();
  await expect(page.getByTestId("access-row").first()).toContainText("Budget bot");
  await expect(page.getByRole("columnheader", { name: "Edge status" })).toBeVisible();
});

test("an SRE sees dependents of a failing service grouped by depth", async ({ page }) => {
  await openFromNav(page);
  await page
    .getByTestId("question-dependents")
    .getByLabel(/Service or tool id/)
    .fill(ACCESS_NODE_SERVICE);
  await page.getByTestId("run-dependents").click();
  const groups = page.getByTestId("depth-group");
  await expect(groups).toHaveCount(3);
  await expect(groups.nth(0)).toContainText("Depth 1");
  await expect(groups.nth(1)).toContainText("Depth 2");
  await expect(groups.nth(2)).toContainText("Depth 3");
  await expect(groups.nth(1).getByTestId("access-row")).toHaveCount(2);
});

test("a truncated scan shows the partial-result banner", async ({ page }) => {
  await openFromNav(page);
  await askWriters(page, ACCESS_ASSET_TRUNCATED);
  const banner = page.getByTestId("partial-banner");
  await expect(banner).toBeVisible();
  await expect(banner).toContainText("partial");
  await expect(banner).toContainText("asset limit");
});

test("a forbidden asset shows the forbidden state", async ({ page }) => {
  await openFromNav(page);
  await askWriters(page, ACCESS_ASSET_FORBIDDEN);
  await expect(page.getByTestId("forbidden-state")).toBeVisible();
  await expect(page.getByTestId("access-row")).toHaveCount(0);
});

test("a forbidden node shows the forbidden state for dependents", async ({ page }) => {
  await openFromNav(page);
  await page
    .getByTestId("question-dependents")
    .getByLabel(/Service or tool id/)
    .fill(ACCESS_NODE_FORBIDDEN);
  await page.getByTestId("run-dependents").click();
  await expect(page.getByTestId("forbidden-state")).toBeVisible();
});

test("an empty result shows the empty state", async ({ page }) => {
  await openFromNav(page);
  await askWriters(page, ACCESS_ASSET_EMPTY);
  await expect(page.getByTestId("access-empty")).toBeVisible();
  await expect(page.getByTestId("access-row")).toHaveCount(0);
});

test("unassessed assets render as not assessed, never as none", async ({ page }) => {
  await openFromNav(page);
  await page.getByLabel("Include assets that are not assessed").check();
  await askWriters(page, ACCESS_ASSET_LEDGER);
  const section = page.getByTestId("unassessed-section");
  await expect(section).toBeVisible();
  await expect(section).toContainText("Not assessed");
  const rows = page.getByTestId("unassessed-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText("not assessed");
});

test("keyboard only: one question is asked and answered without a pointer", async ({ page }) => {
  await openFromNav(page);
  await pickAsset(page, ACCESS_ASSET_LEDGER);
  const run = page.getByTestId("run-writes");
  await expect(run).toBeEnabled();
  await run.focus();
  await expect(run).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("access-row").first()).toBeVisible();
  await expect(page.getByTestId("access-results")).toBeVisible();
});

for (const mode of MODES) {
  test(`axe: the page with results on screen in ${mode}`, async ({ page }) => {
    await seedPreferences(page, { mode });
    await openFromNav(page);
    await askWriters(page, ACCESS_ASSET_LEDGER);
    await expect(page.getByTestId("access-row").first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    const { violations } = await analyze(page);
    expect(blocking(violations), describeBlocking(violations)).toEqual([]);
    expect(violations.map((v) => `${v.id}:${String(v.nodes.length)}`)).toEqual([]);
  });
}
