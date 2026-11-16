import { expect, test } from "../../e2e-support/fixtures.ts";
import { SOURCES_PRICE_SHEET_NEWEST } from "../../mock-api/features/admin-sources.ts";
import { actAsAdmin, axeViolations } from "./support.ts";

// PRP-57: upload a price sheet; the newest version is marked; amounts stay decimal strings.

test.describe.configure({ mode: "serial" });

test("an admin uploads a price sheet and sees its version", async ({ page }) => {
  await actAsAdmin(page);
  await page.goto("/admin/pricing");
  const rows = page.getByTestId("price-sheet-row");
  await expect(rows.first()).toBeVisible();
  await expect(rows.filter({ hasText: SOURCES_PRICE_SHEET_NEWEST })).toContainText("Newest");
  await expect(page.getByTestId("budget-row").first()).toContainText("1500.10 USD");

  await page.getByLabel(/Snapshot id/).fill("azure-e2e-upload");
  await page.getByLabel(/Source URL/).fill("https://prices.example.invalid/e2e");
  await page.getByLabel(/Retrieval date/).fill("2026-12-02");
  await page.getByLabel(/Effective date/).fill("2026-12-01");
  await page
    .getByLabel(/Rows \(JSON array\)/)
    .fill(
      '[{"service_name":"Azure OpenAI","sku_name":"gpt","unit_of_measure":"1K","retail_price":"0.000150"}]',
    );
  await page.getByRole("button", { name: "Upload price sheet" }).click();
  await expect(page.getByTestId("upload-done")).toContainText("created");
  await expect(rows.filter({ hasText: "azure-e2e-upload" })).toContainText("Newest");
  expect(await axeViolations(page)).toEqual([]);
});
