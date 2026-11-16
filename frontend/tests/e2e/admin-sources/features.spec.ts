import { expect, test } from "../../e2e-support/fixtures.ts";
import {
  SOURCES_BAD_ENDPOINT,
  SOURCES_CROSS_CLOUD_TEXT,
} from "../../mock-api/features/admin-sources.ts";
import { actAsAdmin, axeViolations } from "./support.ts";

// PRP-57: save a feature setting (restart notice and diff) and see the validator text on a 422.

test.describe.configure({ mode: "serial" });

test("an admin saves a setting and sees the restart notice and the diff", async ({ page }) => {
  await actAsAdmin(page);
  await page.goto("/admin/features");
  const card = page.locator("[data-testid='setting-card'][data-key='copilot']");
  await expect(card).toBeVisible();
  await expect(card.getByTestId("setting-meta")).toContainText("stored");

  await card.getByLabel(/Copilot model Deployment name/).fill("gpt-e2e-next");
  await card.getByRole("button", { name: "Save setting: Copilot model" }).click();
  const dialog = page.getByTestId("change-confirm-dialog");
  await expect(dialog.getByTestId("change-diff")).toContainText("gpt-e2e-next");
  await dialog.getByRole("button", { name: "Confirm change" }).click();

  await expect(card.getByTestId("setting-saved")).toContainText("restart");
  await expect(card.getByTestId("setting-result-diff")).toContainText("/copilot/deployment");
  await expect(page.getByTestId("write-targets-note")).toContainText("PRP-54");
  expect(await axeViolations(page)).toEqual([]);
});

test("the validator text of a 422 is shown", async ({ page }) => {
  await actAsAdmin(page);
  await page.goto("/admin/features");
  const card = page.locator("[data-testid='setting-card'][data-key='copilot']");
  await card.getByLabel(/Copilot model Endpoint/).fill(`${SOURCES_BAD_ENDPOINT}/x`);
  await card.getByRole("button", { name: "Save setting: Copilot model" }).click();
  await page
    .getByTestId("change-confirm-dialog")
    .getByRole("button", { name: "Confirm change" })
    .click();
  await expect(page.getByTestId("setting-error")).toContainText(SOURCES_CROSS_CLOUD_TEXT);
});
