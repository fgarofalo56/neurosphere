import { expect, test } from "../../e2e-support/fixtures.ts";
import { actAsAdmin, axeViolations } from "./support.ts";

// PRP-57: create a connector configuration with a credential reference; a pasted value is blocked.

test.describe.configure({ mode: "serial" });

test("an admin creates a connector with a Key Vault reference", async ({ page }) => {
  await actAsAdmin(page);
  await page.goto("/admin/sources/connectors");
  await expect(page.getByTestId("connector-row").first()).toBeVisible();
  await expect(page.getByTestId("restart-note")).toContainText("Key Vault Secrets User");

  await page.getByRole("button", { name: "Create connector" }).click();
  const dialog = page.getByTestId("change-confirm-dialog");
  await dialog.getByLabel(/Connector id/).fill("otel-e2e");
  await dialog.getByLabel("Connector kind").selectOption("otel");
  await dialog.getByLabel(/Finance/).check();
  await dialog.getByLabel("Credential type").selectOption("key_vault_secret");

  await dialog.getByLabel(/Key Vault secret URI/).fill("hunter2-not-a-reference");
  await expect(dialog.getByText(/never accepted/)).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Confirm change" })).toBeDisabled();

  await dialog
    .getByLabel(/Key Vault secret URI/)
    .fill("https://kv-e2e.vault.azure.net/secrets/otel-token");
  await dialog.getByRole("button", { name: "Confirm change" }).click();

  await expect(page.getByTestId("change-done")).toBeVisible();
  await expect(page.getByTestId("connector-warnings")).toContainText("producer_not_in_store");
  await expect(page.getByTestId("connector-row").filter({ hasText: "otel-e2e" })).toBeVisible();
  expect(await axeViolations(page)).toEqual([]);
});
