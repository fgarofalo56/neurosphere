import { expect, test } from "../../e2e-support/fixtures.ts";
import {
  ADMIN_DOMAIN_FINANCE,
  ADMIN_PRINCIPAL_FORBIDDEN,
  ADMIN_PRINCIPAL_ID,
  ADMIN_PRINCIPAL_STALE,
} from "../../mock-api/features/admin-core.ts";
import { REASON, actAs, axeViolations } from "./support.ts";

// PRP-53 items 3 and 7: identity administration against the mock API. The writes change the mock's
// in-memory principal, so the specs run one after another and put back what they change.
test.describe.configure({ mode: "serial" });

const detail = (id: string): string =>
  `/admin/identity/principal?principal_id=${encodeURIComponent(id)}`;

test("an admin lists principals and opens one", async ({ page }) => {
  await actAs(page, "Admin");
  await page.goto("/admin/identity");
  await expect(page.getByTestId("principal-row")).toHaveCount(4);
  await page.getByRole("link", { name: ADMIN_PRINCIPAL_ID }).click();
  await expect(page.getByTestId("principal-etag")).toBeVisible();
  await expect(page.getByTestId("assignment-row").first()).toContainText("analyst");
  await expect(page.getByTestId("assignment-row").filter({ hasText: "Expired" })).toHaveCount(1);
});

test("an admin assigns a role through the confirm dialog", async ({ page }) => {
  await actAs(page, "Admin");
  await page.goto(detail(ADMIN_PRINCIPAL_ID));
  await expect(page.getByTestId("assignment-row").first()).toBeVisible();
  const before = await page.getByTestId("assignment-row").count();
  await page.getByRole("button", { name: "Assign role" }).click();
  const dialog = page.getByTestId("change-confirm-dialog");
  await expect(dialog.getByTestId("change-target")).toHaveText(ADMIN_PRINCIPAL_ID);
  await expect(dialog.getByTestId("change-version")).toContainText("principal-");
  const confirm = dialog.getByRole("button", { name: "Confirm change" });
  await expect(confirm).toBeDisabled();
  await dialog.getByLabel(/Domain ids/).fill(ADMIN_DOMAIN_FINANCE);
  await dialog.getByLabel(/Reason code/).fill(REASON);
  await expect(dialog.getByTestId("change-diff")).toContainText(
    `viewer on ${ADMIN_DOMAIN_FINANCE}`,
  );
  expect(await axeViolations(page)).toEqual([]);
  await confirm.click();
  await expect(page.getByTestId("change-done")).toBeVisible();
  await expect(page.getByTestId("assignment-row")).toHaveCount(before + 1);
});

test("revoking shows a persistent banner and lifting clears it", async ({ page }) => {
  await actAs(page, "Admin");
  await page.goto(detail(ADMIN_PRINCIPAL_ID));
  await expect(page.getByTestId("revoked-banner")).toHaveCount(0);
  await page.getByRole("button", { name: "Revoke principal" }).click();
  let dialog = page.getByTestId("change-confirm-dialog");
  await dialog.getByLabel(/Reason code/).fill("offboarding");
  await dialog.getByRole("button", { name: "Confirm change" }).click();
  await expect(page.getByTestId("revoked-banner")).toContainText("until_lifted");
  await page.reload();
  await expect(page.getByTestId("revoked-banner")).toBeVisible();
  await page.getByRole("button", { name: "Lift revocation" }).click();
  dialog = page.getByTestId("change-confirm-dialog");
  await dialog.getByLabel(/Reason code/).fill("mistake");
  await dialog.getByRole("button", { name: "Confirm change" }).click();
  await expect(page.getByTestId("revoked-banner")).toHaveCount(0);
});

test("a stale write shows reload guidance", async ({ page }) => {
  await actAs(page, "Admin");
  await page.goto(detail(ADMIN_PRINCIPAL_STALE));
  await page.getByRole("button", { name: "Add domain membership" }).click();
  const dialog = page.getByTestId("change-confirm-dialog");
  await dialog.getByLabel(/Domain id/).fill(ADMIN_DOMAIN_FINANCE);
  await dialog.getByLabel(/Reason code/).fill(REASON);
  await dialog.getByRole("button", { name: "Confirm change" }).click();
  await expect(dialog.getByTestId("change-error")).toContainText("changed since you loaded");
});

test("a principal outside the caller's scope shows the forbidden state", async ({ page }) => {
  await actAs(page, "Admin");
  await page.goto(detail(ADMIN_PRINCIPAL_FORBIDDEN));
  await expect(page.getByTestId("forbidden-state")).toBeVisible();
  await expect(page.getByRole("button", { name: "Assign role" })).toHaveCount(0);
});

test("a viewer token gets the forbidden state on the principal list", async ({ page }) => {
  await page.goto("/admin/identity");
  await expect(page.getByTestId("forbidden-state")).toBeVisible();
  await expect(page.getByTestId("principal-row")).toHaveCount(0);
});
