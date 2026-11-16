import { expect, test } from "../../e2e-support/fixtures.ts";
import { ADMIN_AUDIT_COUNT, ADMIN_AUDIT_DENIED_COUNT } from "../../mock-api/features/admin-core.ts";
import { actAs, axeViolations } from "./support.ts";

// PRP-53 items 6 and 7: audit search, denials, the SIEM panel and export against the mock API.

test("an admin pages the search by the server cursor and filters it", async ({ page }) => {
  await actAs(page, "Admin");
  await page.goto("/admin/audit");
  await expect(page.getByTestId("audit-row")).toHaveCount(25);
  await page.getByRole("button", { name: "Next page" }).click();
  await expect(page.getByTestId("audit-row")).toHaveCount(ADMIN_AUDIT_COUNT - 25);
  await expect(page.getByRole("button", { name: "Next page" })).toHaveCount(0);

  await page.getByLabel("Kind").selectOption("denied");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByTestId("audit-row")).toHaveCount(ADMIN_AUDIT_DENIED_COUNT);
  expect(await axeViolations(page)).toEqual([]);
});

test("the denials tab and the SIEM panel are shown", async ({ page }) => {
  await actAs(page, "Admin");
  await page.goto("/admin/audit");
  await expect(page.getByTestId("siem-status")).toContainText("eventhubs");
  await expect(page.getByTestId("siem-failures")).toHaveText("0");
  await page.getByRole("tab", { name: "Denials" }).click();
  await expect(page.getByTestId("audit-row")).toHaveCount(ADMIN_AUDIT_DENIED_COUNT);
});

test("an admin exports NDJSON and CSV with the row cap and notice shown", async ({ page }) => {
  await actAs(page, "Admin");
  await page.goto("/admin/audit");
  await expect(page.getByTestId("export-cap")).toContainText("10,000");
  await expect(page.getByTestId("export-notice")).toBeVisible();
  for (const [button, file] of [
    ["Export CSV", "audit-export.csv"],
    ["Export NDJSON", "audit-export.ndjson"],
  ] as const) {
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: button }).click();
    expect((await download).suggestedFilename()).toBe(file);
    await expect(page.getByTestId("export-done")).toContainText(`${ADMIN_AUDIT_COUNT} rows`);
  }
});

test("an auditor can search but export is disabled with an explanation", async ({ page }) => {
  await actAs(page, "Auditor");
  await page.goto("/admin/audit");
  await expect(page.getByTestId("audit-row").first()).toBeVisible();
  await page.getByRole("button", { name: "Export CSV" }).click();
  await expect(page.getByTestId("export-forbidden")).toBeVisible();
  await expect(page.getByRole("button", { name: "Export CSV" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Export NDJSON" })).toBeDisabled();
  await expect(page.getByTestId("audit-row").first()).toBeVisible();
});

test("a viewer token gets the forbidden state", async ({ page }) => {
  await page.goto("/admin/audit");
  await expect(page.getByTestId("forbidden-state").first()).toBeVisible();
  await expect(page.getByTestId("audit-row")).toHaveCount(0);
});
