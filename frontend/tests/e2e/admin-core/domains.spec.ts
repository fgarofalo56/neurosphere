import { expect, test } from "../../e2e-support/fixtures.ts";
import { ADMIN_DOMAIN_RESERVED, ADMIN_RESERVED_TEXT } from "../../mock-api/features/admin-core.ts";
import { actAs } from "./support.ts";

// PRP-53 items 4 and 7: the domain registry against the mock API.

async function fillCreate(
  page: import("@playwright/test").Page,
  domainId: string,
  name: string,
): Promise<void> {
  await page.getByRole("button", { name: "Create domain" }).click();
  const dialog = page.getByTestId("change-confirm-dialog");
  await dialog.getByLabel(/Domain id/).fill(domainId);
  await dialog.getByLabel(/Display name/).fill(name);
  await dialog.getByLabel(/Residency region/).fill("eastus");
}

test("an admin creates a domain and retires it", async ({ page }) => {
  await actAs(page, "Admin");
  await page.goto("/admin/domains");
  await expect(page.getByTestId("domain-row").first()).toBeVisible();
  const id = `commercial:e2e:catalog:domain:ops-${Date.now()}`;
  await fillCreate(page, id, "Ops e2e");
  const dialog = page.getByTestId("change-confirm-dialog");
  await expect(dialog.getByTestId("change-diff")).toContainText("Ops e2e (internal, eastus)");
  await dialog.getByRole("button", { name: "Confirm change" }).click();
  const row = page.getByTestId("domain-row").filter({ hasText: id });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Retire Ops e2e" }).click();
  const retire = page.getByTestId("change-confirm-dialog");
  await expect(retire.getByTestId("change-target")).toHaveText(id);
  await expect(retire.getByTestId("change-version")).toContainText("domain-");
  await retire.getByRole("button", { name: "Confirm change" }).click();
  // A retired domain leaves the default list.
  await expect(page.getByTestId("domain-row").filter({ hasText: id })).toHaveCount(0);
});

test("a reserved name shows the API's text unchanged", async ({ page }) => {
  await actAs(page, "Admin");
  await page.goto("/admin/domains");
  await fillCreate(page, ADMIN_DOMAIN_RESERVED, "Reserved");
  const dialog = page.getByTestId("change-confirm-dialog");
  await dialog.getByRole("button", { name: "Confirm change" }).click();
  await expect(dialog.getByTestId("change-error")).toContainText(ADMIN_RESERVED_TEXT);
});

test("the control domain cannot be retired from the UI", async ({ page }) => {
  await actAs(page, "Admin");
  await page.goto("/admin/domains");
  const button = page.getByRole("button", { name: "Retire Control" });
  await expect(button).toBeDisabled();
  await expect(button).toHaveAttribute("title", /control domain cannot be retired/);
});

test("a viewer token gets the forbidden state", async ({ page }) => {
  await page.goto("/admin/domains");
  await expect(page.getByTestId("forbidden-state")).toBeVisible();
  await expect(page.getByTestId("domain-row")).toHaveCount(0);
});
