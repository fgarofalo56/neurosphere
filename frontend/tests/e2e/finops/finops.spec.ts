import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test } from "../../e2e-support/fixtures.ts";
import { WCAG_TAGS } from "../../helpers/axe.ts";
import { DOMAIN_OK } from "../../mock-api/server.ts";

// PRP-31 item 6: the FinOps forecast and federation pages against the mock API (synthetic data).

const FORECAST = `/finops/forecast?domain_id=${encodeURIComponent(DOMAIN_OK)}`;
const FEDERATION = `/federation?domain_id=${encodeURIComponent(DOMAIN_OK)}`;
const MODES = ["light", "dark", "high-contrast"] as const;

/** Same rules as `axeViolations`, minus Fluent's own focus sentinels (see overview.spec.ts). */
async function axeViolationsIgnoringTabster(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags([...WCAG_TAGS])
    .exclude("[data-tabster-dummy]")
    .analyze();
  return results.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }));
}

async function seedMode(page: Page, mode: (typeof MODES)[number]): Promise<void> {
  await page.addInitScript((m) => {
    window.localStorage.setItem("ns.theme", JSON.stringify({ packId: "default", themeName: m }));
  }, mode);
}

test("forecast shows estimated and invoiced separately with a method card and price versions", async ({
  page,
}) => {
  await page.goto(FORECAST);
  const est = page.getByTestId("series-estimated");
  const inv = page.getByTestId("series-invoiced");
  await expect(est).toBeVisible();
  await expect(inv).toBeVisible();
  await expect(est.getByTestId("chart-estimated")).toBeVisible();
  await expect(inv.getByTestId("chart-invoiced")).toBeVisible();
  await expect(est.getByTestId("band-estimated")).toContainText("dashed");
  await expect(est.getByTestId("table-estimated")).toBeVisible();
  await expect(page.getByTestId("method-name")).toHaveText("linear_trend_ols");
  await expect(page.getByTestId("method-confidence")).toHaveText("95%");
  await expect(page.getByTestId("price-versions")).toContainText("synthetic-prices-2026-10");
  await expect(est.getByTestId("incomplete-estimated")).toBeVisible();
  await expect(page.getByTestId("forecast-body")).not.toContainText(/saving/i);
});

test("an unavailable forecast says why and the controls are bounded", async ({ page }) => {
  const api = page.waitForResponse((r) => r.url().includes("/forecast") && r.status() === 200);
  await page.goto(`${FORECAST}&currency=EUR&history_days=14&horizon_days=7`);
  const url = new URL((await api).url());
  expect(url.searchParams.get("history_days")).toBe("14");
  expect(url.searchParams.get("horizon_days")).toBe("7");
  await expect(page.getByTestId("forecast-unavailable-estimated")).toContainText(
    "forecast unavailable: insufficient_complete_history",
  );
  await expect(page.getByTestId("forecast-unavailable-invoiced")).toBeVisible();
});

test("a domain the caller cannot read shows the forbidden state", async ({ page }) => {
  await page.goto("/finops/forecast?domain_id=commercial%3Ae2e%3Asandbox%3Adomain%3Aforbidden");
  await expect(page.getByTestId("forbidden-state")).toBeVisible();
});

test("federation lists cell outcomes, badges and per-currency totals", async ({ page }) => {
  await page.goto(FEDERATION);
  await expect(page.getByTestId("cell-cell-a")).toContainText("ok");
  await expect(page.getByTestId("cell-cell-b")).toContainText("denied");
  await expect(page.getByTestId("cell-cell-b")).toContainText("not included");
  await expect(page.getByTestId("cell-cell-c")).toContainText("unavailable");
  await expect(page.getByTestId("badge-complete")).toHaveText("incomplete");
  await expect(page.getByTestId("badge-truncated")).toHaveText("not truncated");
  await expect(page.getByTestId("totals-USD")).toContainText("unknown");
  await expect(page.getByTestId("totals-EUR")).toBeVisible();
});

test("federation window and cell filter change the request", async ({ page }) => {
  await page.goto(`${FEDERATION}&days=90`);
  await expect(page.getByTestId("badge-truncated")).toHaveText("truncated");
  await page.goto(`${FEDERATION}&days=30&cell=cell-a`);
  await expect(page.getByTestId("badge-complete")).toHaveText("complete");
  await expect(page.getByTestId("cell-cell-a")).toBeVisible();
  await expect(page.getByTestId("cell-cell-b")).toHaveCount(0);
});

for (const mode of MODES) {
  test(`forecast has no axe violations in ${mode}`, async ({ page }) => {
    await seedMode(page, mode);
    await page.goto(FORECAST);
    await expect(page.getByTestId("series-invoiced")).toBeVisible();
    await expect(page.getByTestId("chart-estimated")).toBeVisible();
    expect(await axeViolationsIgnoringTabster(page)).toEqual([]);
  });

  test(`federation has no axe violations in ${mode}`, async ({ page }) => {
    await seedMode(page, mode);
    await page.goto(FEDERATION);
    await expect(page.getByTestId("totals-USD")).toBeVisible();
    expect(await axeViolationsIgnoringTabster(page)).toEqual([]);
  });
}
