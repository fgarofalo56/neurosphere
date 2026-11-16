import { expect, test } from "../../e2e-support/fixtures.ts";
import { SOURCES_SECRET } from "../../mock-api/features/admin-sources.ts";
import { actAsAdmin, axeViolations } from "./support.ts";

// PRP-57: create a producer; the secret is shown once and is gone after confirming and on reload.

test.describe.configure({ mode: "serial" });

test("the producer secret is shown once, then gone", async ({ page }) => {
  await actAsAdmin(page);
  await page.goto("/admin/sources/producers");
  await expect(page.getByTestId("producer-row").first()).toBeVisible();

  await page.getByRole("button", { name: "Create producer" }).click();
  const dialog = page.getByTestId("change-confirm-dialog");
  await dialog.getByLabel(/Producer id/).fill("ingest-e2e-new");
  await dialog.getByLabel(/Sources/).fill("apim-e2e gateway");
  await dialog.getByRole("button", { name: "Confirm change" }).click();

  const secretDialog = page.getByTestId("secret-dialog");
  await expect(secretDialog.getByTestId("secret-value")).toHaveText(SOURCES_SECRET);
  expect(await axeViolations(page)).toEqual([]);
  await expect(page).not.toHaveURL(new RegExp(SOURCES_SECRET));

  await secretDialog.getByRole("button", { name: "I stored it" }).click();
  await expect(page.getByTestId("secret-dialog")).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText(SOURCES_SECRET);
  await expect(
    page.getByTestId("producer-row").filter({ hasText: "ingest-e2e-new" }),
  ).toBeVisible();

  await page.reload();
  await expect(page.getByTestId("producer-row").first()).toBeVisible();
  await expect(page.locator("body")).not.toContainText(SOURCES_SECRET);
});

test("a viewer token gets the forbidden state", async ({ page }) => {
  await page.goto("/admin/sources/producers");
  await expect(page.getByTestId("forbidden-state").first()).toBeVisible();
});
