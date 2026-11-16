import { expect, test } from "../../e2e-support/fixtures.ts";
import { actAsAdmin, axeViolations } from "./support.ts";

// PRP-57: dry run first; commit is enabled only for the payload that passed it.

test.describe.configure({ mode: "serial" });

test("dry run, then import the same payload", async ({ page }) => {
  await actAsAdmin(page);
  await page.goto("/admin/catalog-import");
  const field = page.getByLabel(/Entity documents/);
  const commit = page.getByRole("button", { name: "Commit import" });
  await expect(commit).toBeDisabled();

  await field.fill('[{"id":"e2e-a"},{"id":"e2e-b","reject":true}]');
  await page.getByRole("button", { name: "Dry run" }).click();
  await expect(page.getByTestId("import-row")).toHaveCount(2);
  await expect(page.getByTestId("import-summary")).toContainText("found problems");
  await expect(commit).toBeDisabled();

  await field.fill('[{"id":"e2e-a"},{"id":"e2e-b"}]');
  await expect(commit).toBeDisabled();
  await page.getByRole("button", { name: "Dry run" }).click();
  await expect(page.getByTestId("import-summary")).toContainText("Dry run is clean");
  await expect(commit).toBeEnabled();
  expect(await axeViolations(page)).toEqual([]);

  await field.fill('[{"id":"e2e-a"},{"id":"e2e-changed"}]');
  await expect(commit).toBeDisabled();
  await field.fill('[{"id":"e2e-a"},{"id":"e2e-b"}]');
  await page.getByRole("button", { name: "Dry run" }).click();
  await expect(commit).toBeEnabled();
  await commit.click();
  await expect(page.getByTestId("import-summary")).toContainText("Import committed");
  await expect(page.getByTestId("import-row").first()).toContainText("created");
});

test("an oversized payload is blocked with the limit stated", async ({ page }) => {
  await actAsAdmin(page);
  await page.goto("/admin/catalog-import");
  const many = JSON.stringify(Array.from({ length: 101 }, (_, i) => ({ id: `e${i}` })));
  await page.getByLabel(/Entity documents/).fill(many);
  await expect(page.getByText(/limit is 100/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Dry run" })).toBeDisabled();
});
