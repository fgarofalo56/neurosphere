import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test } from "../e2e-support/fixtures.ts";
import { WCAG_TAGS } from "../helpers/axe.ts";
import { DOMAIN_OK } from "../mock-api/server.ts";

// PRP-28 item 8: the role-aware overview tiles against the mock API. The stub caller holds only
// the Viewer role, so the cost, map and reports tiles render and the approval tiles do not.

/** Same rules as `axeViolations`, minus Fluent's own focus sentinels (see copilot.spec.ts). */
async function axeViolationsIgnoringTabster(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags([...WCAG_TAGS])
    .exclude("[data-tabster-dummy]")
    .analyze();
  return results.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }));
}

const HOME = `/?domain_id=${encodeURIComponent(DOMAIN_OK)}`;

test("tiles render for the Viewer with per-currency cost and domain-scoped links", async ({
  page,
}) => {
  await page.goto(HOME);
  const cost = page.getByTestId("tile-cost");
  await expect(cost.getByTestId("cost-row").first()).toBeVisible();
  await expect(cost).toContainText("USD");
  await expect(page.getByTestId("tile-map").getByTestId("map-coverage")).toBeVisible();
  await expect(page.getByTestId("tile-reports")).toBeVisible();
  await expect(page.getByTestId("tile-review")).toHaveCount(0);
  await expect(page.getByTestId("tile-awaiting")).toHaveCount(0);
  const d = encodeURIComponent(DOMAIN_OK);
  await expect(cost.getByRole("link")).toHaveAttribute("href", `/dashboards/cost?domain_id=${d}`);
});

test("the cost KPI covers the last 7 days in one call and draws a sparkline per currency series", async ({
  page,
}) => {
  const api = page.waitForResponse(
    (r) => r.url().includes("/dashboards/domains/") && r.status() === 200,
  );
  await page.goto(HOME);
  expect(new URL((await api).url()).searchParams.get("days")).toBe("7");
  const row = page.getByTestId("tile-cost").getByTestId("cost-row").first();
  await expect(row.getByRole("img")).toBeVisible();
  await expect(page.getByTestId("tile-cost")).toContainText("Cost, last 7 days");
});

test("a tile link opens its feature on the same domain", async ({ page }) => {
  await page.goto(HOME);
  await page.getByTestId("tile-reports").getByRole("link").click();
  await expect(page).toHaveURL(new RegExp(`/reports\\?domain_id=${encodeURIComponent(DOMAIN_OK)}`));
});

test("overview has no axe violations", async ({ page }) => {
  await page.goto(HOME);
  await expect(page.getByTestId("tile-cost").getByTestId("cost-row").first()).toBeVisible();
  await expect(page.getByTestId("reports-count")).toBeVisible();
  expect(await axeViolationsIgnoringTabster(page)).toEqual([]);
});
