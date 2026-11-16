import { expect, test } from "../../e2e-support/fixtures.ts";
import { ADMIN_SECRET_PROBE, ADMIN_SETTING_KEYS } from "../../mock-api/features/admin-core.ts";
import { actAs } from "./support.ts";

// PRP-53 items 5 and 7: system status, the first-run checklist and the stored-setting summary.

test("an admin reads components, the checklist and the six setting keys", async ({ page }) => {
  await actAs(page, "Admin");
  await page.goto("/admin/system");
  await expect(page.getByTestId("component-row")).toHaveCount(4);
  await expect(page.getByTestId("ready-state")).toContainText("not ready");
  const checklist = page.getByTestId("checklist-row");
  await expect(checklist).toHaveCount(5);
  await expect(checklist.nth(1)).toContainText("To do");
  await expect(checklist.nth(2)).toContainText("Blocked");
  await expect(page.getByTestId("setting-row")).toHaveCount(ADMIN_SETTING_KEYS.length);
  await expect(page.getByTestId("setting-row").first()).toContainText("Restart required");
});

test("no configuration value, host or secret reaches the page", async ({ page }) => {
  await actAs(page, "Admin");
  await page.goto("/admin/system");
  await expect(page.getByTestId("setting-row").first()).toBeVisible();
  const text = (await page.locator("body").textContent()) ?? "";
  expect(text).not.toContain("probe-secret-host");
  expect(text).not.toContain(ADMIN_SECRET_PROBE);
});

test("a viewer token gets the forbidden state instead of an empty page", async ({ page }) => {
  await page.goto("/admin/system");
  await expect(page.getByTestId("forbidden-state").first()).toBeVisible();
  await expect(page.getByTestId("component-row")).toHaveCount(0);
});
